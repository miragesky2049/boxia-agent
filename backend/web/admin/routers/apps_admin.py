"""平台应用管理接口：平台管理员创建/编辑/上下架应用。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.errors import AppError, ValidationError
from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.domain.graph.node_base import ServiceRegistry
from internal.engine.runtime import GraphRuntime
from internal.engine.services.http_service import HttpService
from internal.engine.services.llm_adapter import LLMServiceAdapter, build_model_resolver
from web.deps.auth import PlatformAdminDep, require_platform_admin
from web.deps.db import UowDep
from web.deps.sse import SSE_HEADERS, sse_event

logger = logging.getLogger(__name__)

# 应用管理是产品级平台运营能力：租户子域名管理员无权调用
router = APIRouter(
    prefix="/apps",
    tags=["apps-admin"],
    dependencies=[Depends(require_platform_admin)],
)


def get_app_service(uow: UowDep) -> ApplicationService:
    return ApplicationService(uow)


AppServiceDep = Depends(get_app_service)


class AppCreatePayload(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=2000)


class AppUpdatePayload(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=500)


class GraphPayload(BaseModel):
    graph: dict[str, Any]
    changelog: str = ""


class ListingPayload(BaseModel):
    listed: bool


class EnabledPayload(BaseModel):
    enabled: bool


class VisibilityDepartmentItem(BaseModel):
    department_id: UUID
    include_subtree: bool = True


class VisibilityPayload(BaseModel):
    mode: str = Field(..., pattern="^(all|custom)$")
    departments: list[VisibilityDepartmentItem] = Field(default_factory=list)
    users: list[UUID] = Field(default_factory=list)


class DebugRunPayload(BaseModel):
    graph: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_apps(
    owner_type: str | None = None,
    marketplace_only: bool = False,
    service: ApplicationService = AppServiceDep,
) -> list[dict]:
    """平台应用列表。"""
    return service.list_applications(
        owner_type=owner_type,
        include_marketplace_only=marketplace_only,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_app(
    payload: AppCreatePayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """创建平台应用（未上架）。"""
    app_id = service.create_platform_application(
        name=payload.name,
        description=payload.description,
    )
    return {"application_id": app_id}


@router.get("/{application_id}")
def get_app(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """获取应用详情。"""
    app = service._repo.get_application(application_id)  # noqa: SLF001
    if app is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("应用不存在")
    return app


@router.patch("/{application_id}")
def update_app(
    application_id: UUID,
    payload: AppUpdatePayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """更新应用基本信息。"""
    service.update_application(
        application_id,
        name=payload.name,
        description=payload.description,
        avatar_url=payload.avatar_url,
    )
    return {"ok": True}


@router.get("/{application_id}/graph")
def get_app_graph(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """获取应用的 graph 定义。"""
    graph = service.get_graph(application_id)
    if graph is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("graph 不存在")
    return graph


@router.put("/{application_id}/graph")
def save_app_graph(
    application_id: UUID,
    payload: GraphPayload,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> dict:
    """保存 graph 定义：写整图版本快照 + 审计 + 缓存失效。"""
    actor_id = getattr(principal, "user_id", None) if principal else None
    actor_username = getattr(principal, "username", "") if principal else ""
    return service.save_graph(
        application_id,
        payload.graph,
        changelog=payload.changelog,
        actor_id=actor_id,
        actor_username=actor_username,
    )


@router.get("/{application_id}/graph-versions")
def list_graph_versions(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> list[dict]:
    """列出整图版本历史（替代旧 field-versions）。"""
    return service.list_graph_versions(application_id)


class RollbackGraphPayload(BaseModel):
    version: int


@router.post("/{application_id}/graph-rollback")
def rollback_graph(
    application_id: UUID,
    payload: RollbackGraphPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """回滚到指定历史版本：把该版本 graph 作为新版本再写一次。"""
    return service.rollback_graph(application_id, payload.version)


class TenantConfigPayload(BaseModel):
    tenant_id: UUID
    config_key: str
    config_value: Any


@router.post("/{application_id}/tenant-config", status_code=status.HTTP_201_CREATED)
def set_tenant_config(
    application_id: UUID,
    payload: TenantConfigPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """设置租户级 config 覆盖（key 形如 graph.nodes.{node_id}.config.{field}）。"""
    service.set_tenant_config(
        tenant_id=payload.tenant_id,
        application_id=application_id,
        config_key=payload.config_key,
        config_value=payload.config_value,
    )
    return {"ok": True}


@router.delete("/{application_id}/tenant-config")
def delete_tenant_config(
    application_id: UUID,
    tenant_id: UUID,
    config_key: str,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """删除租户级 config 覆盖。"""
    service.delete_tenant_config(tenant_id, application_id, config_key)
    return {"ok": True}


class PinGraphVersionPayload(BaseModel):
    tenant_id: UUID
    version: int | None = None


@router.post("/{application_id}/graph-pin")
def pin_graph_version(
    application_id: UUID,
    payload: PinGraphVersionPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """租户锁定整图版本；version=None 回到 latest。"""
    service.pin_graph_version(
        tenant_id=payload.tenant_id,
        application_id=application_id,
        version=payload.version,
    )
    return {"ok": True}


@router.post("/{application_id}/listing")
def set_listing(
    application_id: UUID,
    payload: ListingPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """上架 / 下架应用到市场。"""
    service.set_listed_in_market(application_id, payload.listed)
    return {"ok": True}


@router.post("/{application_id}/enabled")
def set_enabled(
    application_id: UUID,
    payload: EnabledPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """启用 / 禁用应用。"""
    service.set_enabled(application_id, payload.enabled)
    return {"ok": True}


@router.get("/{application_id}/visibility")
def get_app_visibility(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """读取应用可见范围设置。"""
    return service.get_visibility(application_id)


@router.put("/{application_id}/visibility")
def replace_app_visibility(
    application_id: UUID,
    payload: VisibilityPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """整体覆盖应用可见范围：mode=all 全员可见；mode=custom 按部门/用户白名单收敛。"""
    return service.replace_visibility(
        application_id,
        mode=payload.mode,
        departments=[d.model_dump() for d in payload.departments],
        users=list(payload.users),
    )


@router.post("/debug/run/stream")
async def debug_run_stream(
    payload: DebugRunPayload,
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> StreamingResponse:
    """画布 SSE 流式试运行：逐节点外抛 node_start / node_end，最后发 result。

    不依赖已保存的应用，直接用画布 graph 跑（前端编辑中实时试运行）。
    仅平台管理员可用；节点数上限保护试运行不被滥用。
    """
    nodes = payload.graph.get("nodes") or []
    if not isinstance(nodes, list) or len(nodes) > 50:
        raise ValidationError("graph 节点数必须在 1-50 之间")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    model_service = ModelService(uow.session)
    services = ServiceRegistry()
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, _principal.tenant_id)),
    )
    services.register("http", HttpService())

    async def _push_node_event(etype: str, evt_payload: dict) -> None:
        await queue.put(sse_event(etype, evt_payload))

    runtime = GraphRuntime(
        canvas_json=payload.graph,
        services=services,
        checkpointer=None,
        on_node_event=_push_node_event,
    )

    async def runner_task() -> None:
        try:
            output = await runtime.invoke(payload.inputs)
            await queue.put(sse_event("result", {"outputs": output}))
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("debug stream failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner_task())

    async def event_stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
