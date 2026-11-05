"""用户端 workflow 端点：schema、流式运行、人审续跑、运行历史、待审批。

- GET  /agents/{id}/workflow/schema
- POST /agents/{id}/workflow/run/stream        SSE
- POST /agents/{id}/workflow/runs/{thread_id}/resume/stream  SSE
- GET  /agents/{id}/runs
- GET  /agents/{id}/approvals
- GET  /runs/{run_id}
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.apps.workflow_service import WorkflowService
from web.deps.apps_services import make_workflow_service
from web.deps.auth import UserAuthDep
from web.deps.db import UowDep
from web.deps.sse import SSE_HEADERS, sse_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-workflow"])


class WorkflowStreamRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = Field(default=None, max_length=200)


class WorkflowResumeRequest(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


def get_workflow_service(
    uow: UowDep,
    principal: UserAuthDep,
) -> WorkflowService:
    return make_workflow_service(uow, principal)


WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]


def _sse_response(service_iter) -> StreamingResponse:
    """把 service 的 (event, data) 异步迭代器包装成 SSE StreamingResponse。

    流外预检在路由内先执行（抛 JSON 4xx）；本函数只负责已开始运行的事件通道。
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event_name, data in service_iter:
                await queue.put(sse_event(event_name, data))
        except Exception as exc:  # noqa: BLE001
            logger.exception("workflow SSE producer failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": "workflow_failed"}))
            await queue.put(sse_event("final", {}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(producer())

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
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/agents/{application_id}/workflow/schema")
async def get_workflow_schema(
    application_id: UUID,
    service: WorkflowServiceDep,
) -> dict:
    """工作流入参 schema：供用户端动态渲染启动表单。"""
    return await service.get_workflow_schema(application_id)


@router.post("/agents/{application_id}/workflow/run/stream")
async def run_workflow_stream(
    application_id: UUID,
    payload: WorkflowStreamRequest,
    service: WorkflowServiceDep,
) -> StreamingResponse:
    """SSE 运行工作流：run_start / node_start / node_end / llm_token / result / interrupted / final。"""
    prepared = await service.prepare_workflow_run(
        application_id,
        inputs=payload.inputs,
        thread_id=payload.thread_id,
    )
    return _sse_response(service.run_workflow_stream(prepared))


@router.post("/agents/{application_id}/workflow/runs/{thread_id}/resume/stream")
async def resume_workflow_stream(
    application_id: UUID,
    thread_id: str,
    payload: WorkflowResumeRequest,
    service: WorkflowServiceDep,
) -> StreamingResponse:
    """SSE 审批续跑：角色校验在流外完成（403 JSON），续跑事件与运行一致。"""
    prepared = await service.prepare_workflow_resume(
        application_id,
        thread_id,
        approved=payload.approved,
        comment=payload.comment,
    )
    return _sse_response(service.resume_workflow_stream(prepared))


@router.get("/agents/{application_id}/runs")
def list_workflow_runs(
    application_id: UUID,
    service: WorkflowServiceDep,
    limit: int = 50,
) -> list[dict]:
    """当前用户在该应用下的运行历史。"""
    return service.list_runs(application_id, limit=limit)


@router.get("/agents/{application_id}/approvals")
def list_workflow_approvals(
    application_id: UUID,
    service: WorkflowServiceDep,
    limit: int = 50,
) -> list[dict]:
    """等待当前用户角色审批的中断运行列表。"""
    return service.list_approvals(application_id, limit=limit)


@router.get("/runs/{run_id}")
def get_workflow_run(
    run_id: UUID,
    service: WorkflowServiceDep,
) -> dict:
    """运行详情（run + 节点执行明细）：发起人或匹配审批角色可见。"""
    return service.get_run_detail(run_id)
