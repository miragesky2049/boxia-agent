"""v4 应用市场接口：浏览产品级应用、自助开通、我的应用列表、租户运行（含人审 interrupt/resume）。"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import NotFoundError, ValidationError
from internal.application.v4.application_service import V4ApplicationService
from internal.application.v4.model_service import V4ModelService
from internal.engine.v4.runner import GraphInterrupted, GraphRunner
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
) -> GraphRunner:
    """构造 GraphRunner：加载 effective_config graph + 租户模型解析器 + 子图加载器 + tool 解析器。"""
    graph = service.build_effective_graph(application_id, tenant_id)
    model_service = V4ModelService(uow.session)
    from internal.application.v4.resource_service import V4ResourceService

    resource_service = V4ResourceService(uow.session)

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
        return {"status": "success", "output": output, "thread_id": runner.thread_id}
    except GraphInterrupted as exc:
        return {
            "status": "waiting_approval",
            "thread_id": runner.thread_id,
            "approval": exc.interrupt_payload,
        }


@router.post("/applications/{application_id}/runs/{thread_id}/resume")
async def resume_application(
    application_id: UUID,
    thread_id: str,
    payload: ResumePayload,
    service: V4ServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """人审节点恢复执行：提交审批结果后继续跑图。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    instance = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
    if instance is None:
        raise NotFoundError("该应用未开通或不存在")

    runner = _build_runner(service, uow, tenant_id, application_id, thread_id=thread_id)
    try:
        output = await runner.resume({"approved": payload.approved, "comment": payload.comment})
        return {"status": "success", "output": output, "thread_id": thread_id}
    except GraphInterrupted as exc:
        return {
            "status": "waiting_approval",
            "thread_id": thread_id,
            "approval": exc.interrupt_payload,
        }
