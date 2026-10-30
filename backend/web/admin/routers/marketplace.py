"""应用市场接口：浏览产品级应用、自助开通、我的应用列表、租户运行（含人审 interrupt/resume）。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.application.apps.application_service import ApplicationService
from internal.engine.runtime import GraphInterrupted, GraphRuntime
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.security.ssrf_guard import validate_outbound_url
from web.deps.auth import AdminAuthDep
from web.deps.db import UowDep
from web.deps.graph import build_runner
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


class SubscribePayload(BaseModel):
    application_id: UUID


class RunPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class ResumePayload(BaseModel):
    approved: bool
    comment: str = ""


def get_app_service(uow: UowDep) -> ApplicationService:
    return ApplicationService(uow)


AppServiceDep = Annotated[ApplicationService, Depends(get_app_service)]


@router.get("/applications")
def list_marketplace(
    service: AppServiceDep,
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    """浏览应用市场（cursor 分页）。"""
    from datetime import datetime
    cursor_dt = datetime.fromisoformat(cursor) if cursor else None
    return service.list_marketplace(cursor_updated_at=cursor_dt, limit=limit)


@router.get("/applications/{application_id}")
def get_marketplace_application(
    application_id: UUID,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """市场应用详情：基本信息 + 当前租户的授权/申请状态。

    返回字段：
    - application: 应用基本信息（name/avatar/description/sale_mode/support_trial/doc_url）
    - my_subscription: 当前租户已开通记录（无则 null）
    - my_latest_apply: 当前租户最近一条申请单（无则 null）
    - inputs: start 节点定义的输入变量（运行表单用）
    """
    from internal.infrastructure.repository.apps.auth_repository import AuthRepository

    app = service._repo.get_marketplace_application(application_id)  # noqa: SLF001
    if app is None:
        raise NotFoundError("应用不存在或未上架市场")

    tenant_id = context.tenant_id
    my_subscription = None
    my_latest_apply = None
    if tenant_id is not None:
        auth_repo = AuthRepository(uow.session)
        my_subscription = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
        my_latest_apply = auth_repo.get_latest_apply(tenant_id, application_id)

    graph = service.build_effective_graph_sync(application_id, tenant_id)
    start_node = next(
        (n for n in graph.get("nodes", []) if n.get("type") == "start"),
        None,
    )
    inputs = (start_node or {}).get("config", {}).get("inputs") or []

    return {
        "application": app,
        "my_subscription": my_subscription,
        "my_latest_apply": my_latest_apply,
        "inputs": inputs,
    }


@router.post("/subscribe")
def subscribe(
    payload: SubscribePayload,
    service: AppServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户自助开通应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.subscribe(context.tenant_id, payload.application_id)


@router.get("/my-apps")
def list_my_apps(
    service: AppServiceDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户查看已开通的应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_my_apps(context.tenant_id)


async def _build_runner(
    service: ApplicationService,
    uow: UowDep,
    context: Any,
    tenant_id: UUID,
    application_id: UUID,
    thread_id: str | None = None,
    run_id: UUID | None = None,
    current_user_id: UUID | None = None,
    actor_username: str | None = None,
) -> GraphRuntime:
    """兼容包装：转发到 web.deps.graph.build_runner。"""
    return await build_runner(
        service,
        uow,
        context,
        tenant_id=tenant_id,
        application_id=application_id,
        thread_id=thread_id,
        run_id=run_id,
        current_user_id=current_user_id,
        actor_username=actor_username,
    )


@router.post("/applications/{application_id}/run")
async def run_application(
    application_id: UUID,
    payload: RunPayload,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
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

    runner = await _build_runner(
        service, uow, context, tenant_id, application_id,
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )
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
    service: AppServiceDep,
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

    run_repo = RunRepository(uow.session)
    pending = run_repo.get_running_by_thread(tenant_id, application_id, thread_id)
    if pending is None:
        raise NotFoundError("没有等待审批的运行记录")

    runner = await _build_runner(
        service, uow, context, tenant_id, application_id,
        thread_id=thread_id, run_id=pending["id"],
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )

    # 人审角色校验：从 checkpointer 取出当前 interrupt payload，比对 assignee_role
    # fail-closed：读不到 interrupt 或节点未配 assignee_role 时拒绝恢复，避免越权放行
    interrupt_state = await runner.get_interrupt_state()
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
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    limit: int = 50,
) -> list[dict]:
    """租户查看某应用的运行历史。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return RunRepository(uow.session).list_runs(
        tenant_id, workflow_id=application_id, limit=limit
    )


@router.get("/applications/{application_id}/inputs")
def get_application_inputs(
    application_id: UUID,
    service: AppServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户查看该应用 start 节点定义的输入变量，用于动态生成运行表单。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    instance = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
    if instance is None:
        raise NotFoundError("该应用未开通或不存在")

    graph = service.build_effective_graph_sync(application_id, tenant_id)
    start_node = next(
        (n for n in graph.get("nodes", []) if n.get("type") == "start"),
        None,
    )
    inputs = (start_node or {}).get("config", {}).get("inputs") or []
    return {"inputs": inputs}


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

    run_repo = RunRepository(uow.session)
    run = run_repo.get_run(run_id)
    if run is None or run["tenant_id"] != tenant_id:
        raise NotFoundError("运行记录不存在")
    return {
        "run": run,
        "node_executions": run_repo.list_node_executions(run_id),
    }


@router.get("/runs/{run_id}/checkpoints")
async def list_run_checkpoints(
    run_id: UUID,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """列出某 run 的 checkpoint 历史（time-travel 用）。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    run_repo = RunRepository(uow.session)
    run = run_repo.get_run(run_id)
    if run is None or run["tenant_id"] != tenant_id:
        raise NotFoundError("运行记录不存在")

    runner = await _build_runner(
        service, uow, context, tenant_id, run["workflow_id"],
        thread_id=run["thread_id"], run_id=run_id,
    )
    history = await runner.list_checkpoint_history(limit=20)
    return {"checkpoints": history}


class ForkPayload(BaseModel):
    checkpoint_id: str
    new_input: dict[str, Any] | None = None


@router.post("/runs/{run_id}/fork")
async def fork_run(
    run_id: UUID,
    payload: ForkPayload,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
) -> dict:
    """从历史 checkpoint 分叉重跑：复制 state 到新 thread，从该状态继续。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    run_repo = RunRepository(uow.session)
    run = run_repo.get_run(run_id)
    if run is None or run["tenant_id"] != tenant_id:
        raise NotFoundError("运行记录不存在")

    # 新 run_id，新 thread 由 runner 内部生成
    new_run_id = uuid.uuid4()
    runner = await _build_runner(
        service, uow, context, tenant_id, run["workflow_id"],
        run_id=new_run_id,
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )

    # 先落一条新 run 记录（fork 用的 graph 直接复用 runner 加载的 graph）
    graph = runner.graph_snapshot if hasattr(runner, "graph_snapshot") else service.build_effective_graph_sync(run["workflow_id"], tenant_id)
    run_repo.insert_run(
        run_id=new_run_id,
        tenant_id=tenant_id,
        workflow_id=run["workflow_id"],
        graph_snapshot=graph,
        input_data=payload.new_input or run["input"],
        thread_id=runner.thread_id,
    )

    try:
        result = await runner.fork_from_checkpoint(
            source_thread_id=run["thread_id"],
            checkpoint_id=payload.checkpoint_id,
            new_input=payload.new_input,
        )
        uow.commit()
        return {
            "status": "success",
            "new_run_id": str(new_run_id),
            "new_thread_id": result["new_thread_id"],
            "output": result["output"],
        }
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "new_run_id": str(new_run_id),
            "new_thread_id": runner.thread_id,
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


# ========== webhook 通知订阅 CRUD ==========
class WebhookPayload(BaseModel):
    event_type: str = Field(..., description="run_finished / run_error / node_error")
    url: str = Field(..., description="回调 URL")
    application_id: UUID | None = Field(default=None, description="空 = 该租户所有应用")


@router.get("/webhooks")
def list_webhooks(
    uow: UowDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户列出自己的 webhook 订阅。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return WebhookRepository(uow.session).list_by_tenant(tenant_id)


@router.post("/webhooks")
def create_webhook(
    payload: WebhookPayload,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """创建 webhook 订阅。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    # SSRF 防护：拒绝 loopback/链路本地/云元数据/组播/保留地址，校验 DNS 解析
    validate_outbound_url(payload.url)
    wid = WebhookRepository(uow.session).create(
        tenant_id=tenant_id,
        event_type=payload.event_type,
        url=payload.url,
        application_id=payload.application_id,
    )
    uow.commit()
    return {"id": str(wid)}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: UUID,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """删除 webhook 订阅。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    WebhookRepository(uow.session).delete(webhook_id, tenant_id)
    uow.commit()
    return {"ok": True}
