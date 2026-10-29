"""v4 应用市场接口：浏览产品级应用、自助开通、我的应用列表、租户运行（含人审 interrupt/resume）。"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.application.v4.application_service import V4ApplicationService
from internal.application.v4.model_service import V4ModelService
from internal.engine.v4.runner import GraphInterrupted, GraphRunner
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)
from internal.infrastructure.repository.v4.run_repository import V4RunRepository
from internal.infrastructure.repository.v4.usage_repository import V4UsageRepository
from web.deps.auth import AdminAuthDep
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v4/marketplace", tags=["v4-marketplace"])


class SubscribePayload(BaseModel):
    application_id: UUID


class RunPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class ResumePayload(BaseModel):
    approved: bool
    comment: str = ""


def get_v4_service(uow: UowDep) -> V4ApplicationService:
    return V4ApplicationService(uow.session)


V4ServiceDep = Annotated[V4ApplicationService, Depends(get_v4_service)]


@router.get("/applications")
def list_marketplace(service: V4ServiceDep) -> list[dict]:
    """浏览应用市场。"""
    return service.list_marketplace()


@router.post("/subscribe")
def subscribe(
    payload: SubscribePayload,
    service: V4ServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户自助开通应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.subscribe(context.tenant_id, payload.application_id)


@router.get("/my-apps")
def list_my_apps(
    service: V4ServiceDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户查看已开通的应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_my_apps(context.tenant_id)


def _build_runner(
    service: V4ApplicationService,
    uow: UowDep,
    tenant_id: UUID,
    application_id: UUID,
    thread_id: str | None = None,
    run_id: UUID | None = None,
) -> GraphRunner:
    """构造 GraphRunner：加载 effective_config graph + 租户模型解析器 + 子图加载器 + tool 解析器。"""
    graph = service.build_effective_graph(application_id, tenant_id)
    model_service = V4ModelService(uow.session)
    from internal.application.v4.resource_service import V4ResourceService

    resource_service = V4ResourceService(uow.session)
    run_repo = V4RunRepository(uow.session)
    usage_repo = V4UsageRepository(uow.session)
    audit_repo = PostgresAuditLogRepository(uow.session)

    def subgraph_loader(child_app_id: str) -> dict:
        """加载子图的 effective graph JSON（按当前租户应用 pin 字段）。"""
        try:
            child_uuid = UUID(child_app_id)
        except ValueError:
            return {}
        try:
            return service.build_effective_graph(child_uuid, tenant_id)
        except Exception:  # noqa: BLE001
            logger.exception("加载子图失败: child_app_id=%s", child_app_id)
            return {}

    def tool_resolver(resource_id: str) -> dict | None:
        """按租户解析 tool 资源：无权访问或不存在返回 None。"""
        try:
            rid = UUID(resource_id)
        except ValueError:
            return None
        return resource_service.resolve_for_tenant(rid, tenant_id)

    return GraphRunner(
        graph=graph,
        tenant_id=tenant_id,
        application_id=application_id,
        model_resolver=lambda mid: model_service.get_client_for_tenant(mid, tenant_id),
        subgraph_loader=subgraph_loader,
        tool_resolver=tool_resolver,
        thread_id=thread_id,
        run_id=run_id,
        run_repo=run_repo,
        usage_repo=usage_repo,
        audit_repo=audit_repo,
    )


@router.post("/applications/{application_id}/run")
async def run_application(
    application_id: UUID,
    payload: RunPayload,
    service: V4ServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """租户运行已开通的应用。

    - 正常完成：{"status": "success", "output": ...}
    - 遇到人审节点：{"status": "waiting_approval", "thread_id": "...", "approval": {...}}
    """
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    instance = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
    if instance is None:
        raise NotFoundError("该应用未开通或不存在")

    runner = _build_runner(service, uow, tenant_id, application_id)
    try:
        output = await runner.invoke(payload.inputs)
        uow.commit()
        return {"status": "success", "output": output, "thread_id": runner.thread_id, "run_id": runner.run_id}
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "thread_id": runner.thread_id,
            "run_id": runner.run_id,
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


@router.post("/applications/{application_id}/runs/{thread_id}/resume")
async def resume_application(
    application_id: UUID,
    thread_id: str,
    payload: ResumePayload,
    service: V4ServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
) -> dict:
    """人审节点恢复执行：提交审批结果后继续跑图。

    resume 前先查 run 表校验 ownership：thread_id 必须属于 (tenant_id, application_id)
    且状态为 interrupted，否则 404。防止跨租户通过伪造 thread_id 接管他人运行。

    同时校验人审节点配置的 assignee_role：当前 principal 的 role_code 必须匹配，
    superadmin 始终放行（超管兜底）。不匹配抛 403。
    """
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    instance = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
    if instance is None:
        raise NotFoundError("该应用未开通或不存在")

    run_repo = V4RunRepository(uow.session)
    pending = run_repo.get_running_by_thread(tenant_id, application_id, thread_id)
    if pending is None:
        raise NotFoundError("没有等待审批的运行记录")

    runner = _build_runner(
        service, uow, tenant_id, application_id,
        thread_id=thread_id, run_id=pending["id"],
    )

    # 人审角色校验：从 checkpointer 取出当前 interrupt payload，比对 assignee_role
    # fail-closed：读不到 interrupt 或节点未配 assignee_role 时拒绝恢复，避免越权放行
    interrupt_state = runner.get_interrupt_state()
    if interrupt_state is None:
        raise ForbiddenError("无法读取人审节点配置，禁止恢复执行")

    required_role = interrupt_state.get("assignee_role")
    if not required_role:
        raise ForbiddenError("人审节点未配置审批角色，禁止恢复执行")

    if principal.role_code != "superadmin" and principal.role_code != required_role:
        raise ForbiddenError(
            f"该人审节点要求角色 {required_role}，当前角色 {principal.role_code} 无权审批"
        )

    try:
        output = await runner.resume({"approved": payload.approved, "comment": payload.comment})
        uow.commit()
        return {"status": "success", "output": output, "thread_id": thread_id, "run_id": pending["id"]}
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "thread_id": thread_id,
            "run_id": pending["id"],
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


@router.get("/applications/{application_id}/runs")
def list_runs(
    application_id: UUID,
    service: V4ServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    limit: int = 50,
) -> list[dict]:
    """租户查看某应用的运行历史。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return V4RunRepository(uow.session).list_runs(
        tenant_id, application_id=application_id, limit=limit
    )


@router.get("/runs/{run_id}")
def get_run_detail(
    run_id: UUID,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """查看运行详情：run 元信息 + 节点执行列表。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    run_repo = V4RunRepository(uow.session)
    run = run_repo.get_run(run_id)
    if run is None or run["tenant_id"] != tenant_id:
        raise NotFoundError("运行记录不存在")
    return {
        "run": run,
        "node_executions": run_repo.list_node_executions(run_id),
    }
