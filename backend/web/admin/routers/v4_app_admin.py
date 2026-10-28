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

from internal.application.errors import AppError
from internal.application.v4.application_service import V4ApplicationService
from internal.application.v4.model_service import V4ModelService
from internal.engine.v4.runner import GraphRunner
from web.deps.db import UowDep
from web.deps.sse import SSE_HEADERS, sse_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v4/apps", tags=["v4-app-admin"])


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
    """保存 graph 定义，返回推断的 runtime_mode。"""
    runtime_mode = service.save_graph(application_id, payload.graph)
    return {"runtime_mode": runtime_mode}


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
) -> StreamingResponse:
    """画布 SSE 流式试运行：逐节点外抛 node_start / node_end，最后发 result。

    不依赖已保存的应用，直接用画布 graph 跑（前端编辑中实时试运行）。
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    model_service = V4ModelService(uow.session)
    model_service.seed_from_settings()

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
            async for event in runner.compiled.astream_events(
                {"input": payload.inputs},
                config={"configurable": {"thread_id": runner.langgraph_thread_id}},
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
