"""v4 平台应用管理接口：平台管理员创建/编辑/上下架应用。"""

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
from internal.application.v4.application_service import V4ApplicationService
from internal.application.v4.model_service import V4ModelService
from internal.engine.v4.runner import GraphRunner
from web.deps.auth import PlatformAdminDep, require_platform_admin
from web.deps.db import UowDep
from web.deps.sse import SSE_HEADERS, sse_event

logger = logging.getLogger(__name__)

# v4 应用管理是产品级平台运营能力：租户子域名管理员无权调用
router = APIRouter(
    prefix="/v4/apps",
    tags=["v4-app-admin"],
    dependencies=[Depends(require_platform_admin)],
)


def get_app_service(uow: UowDep) -> V4ApplicationService:
    return V4ApplicationService(uow.session)


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


class ListingPayload(BaseModel):
    listed: bool


class EnabledPayload(BaseModel):
    enabled: bool


class DebugRunPayload(BaseModel):
    graph: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)


class PinFieldPayload(BaseModel):
    tenant_id: UUID
    field_path: str = Field(..., max_length=500)
    version: int = Field(..., ge=1)


@router.get("")
def list_apps(
    owner_type: str | None = None,
    marketplace_only: bool = False,
    service: V4ApplicationService = AppServiceDep,
) -> list[dict]:
    """平台应用列表。"""
    return service.list_applications(
        owner_type=owner_type,
        include_marketplace_only=marketplace_only,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_app(
    payload: AppCreatePayload,
    service: V4ApplicationService = AppServiceDep,
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
    service: V4ApplicationService = AppServiceDep,
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
    service: V4ApplicationService = AppServiceDep,
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
    service: V4ApplicationService = AppServiceDep,
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
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """保存 graph 定义，返回推断的 runtime_mode 与本次快照的字段版本列表。"""
    return service.save_graph(application_id, payload.graph)


@router.get("/{application_id}/field-versions")
def list_field_versions(
    application_id: UUID,
    field_path: str | None = None,
    service: V4ApplicationService = AppServiceDep,
) -> list[dict]:
    """列出某应用全部字段的版本历史；传 field_path 只看单字段。"""
    return service.list_field_versions(application_id, field_path)


@router.get("/{application_id}/effective-config")
def get_effective_config(
    application_id: UUID,
    tenant_id: UUID | None = None,
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """计算租户视角下的生效 config：pin 字段用 pinned 版本，其余用 latest。"""
    return service.get_effective_config(application_id, tenant_id)


@router.post("/{application_id}/field-pin", status_code=status.HTTP_201_CREATED)
def pin_field(
    application_id: UUID,
    payload: PinFieldPayload,
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """租户把某字段锁定在指定版本。"""
    service.pin_field(
        tenant_id=payload.tenant_id,
        application_id=application_id,
        field_path=payload.field_path,
        version=payload.version,
    )
    return {"ok": True}


@router.delete("/{application_id}/field-pin")
def unpin_field(
    application_id: UUID,
    tenant_id: UUID,
    field_path: str,
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """租户取消某字段的 pin，回到 latest。"""
    service.unpin_field(tenant_id, application_id, field_path)
    return {"ok": True}


@router.post("/{application_id}/listing")
def set_listing(
    application_id: UUID,
    payload: ListingPayload,
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """上架 / 下架应用到市场。"""
    service.set_listed_in_market(application_id, payload.listed)
    return {"ok": True}


@router.post("/{application_id}/enabled")
def set_enabled(
    application_id: UUID,
    payload: EnabledPayload,
    service: V4ApplicationService = AppServiceDep,
) -> dict:
    """启用 / 禁用应用。"""
    service.set_enabled(application_id, payload.enabled)
    return {"ok": True}


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

    model_service = V4ModelService(uow.session)

    async def node_callback(event_type: str, data: dict[str, Any]) -> None:
        await queue.put(sse_event(event_type, data))

    runner = GraphRunner(
        graph=payload.graph,
        model_resolver=lambda mid: model_service.get_client(mid),
    )

    # 用 LangGraph astream_events 逐节点推事件，最后 result 从最终 state 取
    from internal.engine.v4.nodes.builtin import ModelResolverCtx

    async def runner_task() -> None:
        node_started_at: dict[str, float] = {}
        final_state: dict[str, Any] | None = None
        token = ModelResolverCtx.set(lambda mid: model_service.get_client(mid))
        try:
            await runner._ensure_compiled()
            async for event in runner.compiled.astream_events(
                {"input": payload.inputs},
                config={"configurable": {"thread_id": runner.thread_id}},
                version="v2",
            ):
                kind = event["event"]
                name = event["name"]
                # 过滤掉 LangGraph 内部链，只保留用户节点
                if not name or name.startswith("LangGraph") or name in ("Graph", "Channel"):
                    continue
                if kind == "on_chain_start":
                    node_started_at[name] = time.perf_counter()
                    await queue.put(sse_event("node_start", {
                        "node_id": name,
                        "type": name,
                    }))
                elif kind == "on_chain_end":
                    output = (event.get("data") or {}).get("output") or {}
                    duration_ms = int(
                        (time.perf_counter() - node_started_at.get(name, time.perf_counter())) * 1000
                    )
                    await queue.put(sse_event("node_end", {
                        "node_id": name,
                        "type": name,
                        "status": "success",
                        "duration_ms": duration_ms,
                        "output": output if isinstance(output, dict) else {"value": output},
                        "error": "",
                    }))
                    if isinstance(output, dict) and "output" in output:
                        final_state = output
                elif kind == "on_chain_error":
                    err = (event.get("data") or {}).get("error")
                    duration_ms = int(
                        (time.perf_counter() - node_started_at.get(name, time.perf_counter())) * 1000
                    )
                    await queue.put(sse_event("node_end", {
                        "node_id": name,
                        "type": name,
                        "status": "error",
                        "duration_ms": duration_ms,
                        "output": {},
                        "error": str(err),
                    }))

            await queue.put(sse_event("result", {
                "outputs": (final_state or {}).get("output", {}),
            }))
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("v4 debug stream failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            ModelResolverCtx.reset(token)
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
