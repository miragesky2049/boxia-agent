"""用户端 agent 运行接口：同步 JSON + SSE 流式两个版本。"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from internal.application.agent_run_service import AgentRunService
from internal.application.errors import AppError
from internal.engine.runner import AgentRunResult
from web.deps.auth import UserAuthDep
from web.deps.services import AgentRunServiceDep
from web.deps.sse import SSE_HEADERS, sse_event
from web.user.schemas.agent_run import (
    AgentRunRequest,
    AgentRunResponse,
    ToolCallTraceOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["user-agent-run"])


def _to_response(agent_id: UUID, result: AgentRunResult, conversation_id: str) -> AgentRunResponse:
    return AgentRunResponse(
        agent_id=agent_id,
        run_id=result.run_id,
        conversation_id=result.conversation_id or conversation_id,
        content=result.content,
        tool_traces=[ToolCallTraceOut(**trace.__dict__) for trace in result.tool_traces],
        iterations=result.iterations,
        usage=result.usage,
        finish_reason=result.finish_reason,
    )


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_id: UUID,
    body: AgentRunRequest,
    service: AgentRunServiceDep,
    principal: UserAuthDep,
) -> AgentRunResponse:
    """运行一次 agent（同步 JSON，兼容旧客户端）。"""
    conversation_id = body.conversation_id or f"conv_{uuid4().hex[:16]}"
    result = await service.run(
        agent_id=agent_id,
        query=body.query,
        conversation_id=conversation_id,
        user_id=principal.user_id,
        user_name=principal.display_name or principal.username,
        history=[item.model_dump() for item in body.history],
    )
    return _to_response(agent_id, result, conversation_id)


@router.post("/{agent_id}/run/stream")
async def run_agent_stream(
    agent_id: UUID,
    body: AgentRunRequest,
    service: AgentRunServiceDep,
    principal: UserAuthDep,
) -> StreamingResponse:
    """SSE 流式运行 agent：边跑边推 run_start / llm_start / tool_start / final 事件。"""
    conversation_id = body.conversation_id or f"conv_{uuid4().hex[:16]}"

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def enqueue(event: str, data: dict) -> None:
        await queue.put(sse_event(event, data))

    async def event_callback(event: str, data: dict) -> None:
        await enqueue(event, data)

    async def runner() -> None:
        try:
            result = await service.run(
                agent_id=agent_id,
                query=body.query,
                conversation_id=conversation_id,
                user_id=principal.user_id,
                user_name=principal.display_name or principal.username,
                history=[item.model_dump() for item in body.history],
                event_callback=event_callback,
            )
            # final 事件由 runner 自己抛过，但前端要拿完整结果，这里再发一次 result 帧
            await enqueue(
                "result",
                _to_response(agent_id, result, conversation_id).model_dump(mode="json"),
            )
        except AppError as exc:
            await enqueue("error", {"message": exc.message, "code": exc.status_code})
        except Exception as exc:  # noqa: BLE001 - 兜底转 SSE error 帧
            logger.exception("agent stream failed agent=%s", agent_id)
            await enqueue("error", {"message": str(exc), "code": 500})
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


__all__ = ["AgentRunService"]
