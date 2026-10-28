"""用户端工作流运行接口：同步 JSON + SSE 流式两个版本。"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from internal.application.errors import AppError
from internal.application.workflow_run_service import WorkflowRunService
from internal.engine.workflow.executor import WorkflowRunResult
from web.deps.auth import UserAuthDep
from web.deps.services import WorkflowRunServiceDep
from web.deps.sse import SSE_HEADERS, sse_event
from web.user.schemas.workflow_run import (
    WorkflowNodeStateOut,
    WorkflowRunRequest,
    WorkflowRunResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["user-workflow-run"])


def _to_response(workflow_id: UUID, result: WorkflowRunResult) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        workflow_id=workflow_id,
        run_id=result.run_id,
        outputs=result.outputs,
        node_states=[
            WorkflowNodeStateOut(
                node_id=state.node_id,
                type=state.type,
                status=state.status,
                duration_ms=state.duration_ms,
                output=state.output,
                error=state.error,
            )
            for state in result.node_states
        ],
        usage=result.usage,
        finish_reason=result.finish_reason,
    )


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: UUID,
    body: WorkflowRunRequest,
    service: WorkflowRunServiceDep,
    principal: UserAuthDep,
) -> WorkflowRunResponse:
    """运行一次工作流（同步 JSON，兼容旧客户端）。"""
    result = await service.run(
        workflow_id=workflow_id,
        inputs=body.inputs,
        user_id=principal.user_id,
    )
    return _to_response(workflow_id, result)


@router.post("/{workflow_id}/run/stream")
async def run_workflow_stream(
    workflow_id: UUID,
    body: WorkflowRunRequest,
    service: WorkflowRunServiceDep,
    principal: UserAuthDep,
) -> StreamingResponse:
    """SSE 流式运行工作流：边跑边推 node_start / node_end / result 事件。"""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def event_callback(event: str, data: dict) -> None:
        await queue.put(sse_event(event, data))

    async def runner() -> None:
        try:
            result = await service.run(
                workflow_id=workflow_id,
                inputs=body.inputs,
                user_id=principal.user_id,
                event_callback=event_callback,
            )
            await queue.put(
                sse_event(
                    "result",
                    _to_response(workflow_id, result).model_dump(mode="json"),
                )
            )
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001 - 兜底转 SSE error 帧
            logger.exception("workflow stream failed workflow=%s", workflow_id)
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())

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
