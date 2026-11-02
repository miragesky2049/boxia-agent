"""用户端 chat / workflow 运行端点。

- POST /agents/{id}/run/stream   SSE 流式 chat（ReAct 循环，前端 ChatPage 对接）
- POST /agents/{id}/run           非流式 chat（可选，前端已封装未用）
- POST /agents/{id}/workflow/run   workflow 非流式运行（dag）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.apps.chat_service import ChatService
from internal.application.errors import AppError
from web.deps.auth import UserAuthDep
from web.deps.db import UowDep
from web.deps.graph import build_runner
from web.deps.sse import SSE_HEADERS, sse_event
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["user-chat"])


class HistoryMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = ""


class RunStreamRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = None
    history: list[HistoryMessage] | None = None


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    # 对话流运行上下文：消息/会话类节点未显式连线会话 ID 时回退使用
    conversation_id: UUID | None = None


class ChatflowRunRequest(BaseModel):
    # 纯续跑（resume）时允许为空；message 与 resume 至少提供一个是服务层校验
    message: str = Field("", max_length=8000)
    conversation_id: UUID | None = None
    thread_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    # 问答节点/人审中断后的续跑载荷，如 {"answer": "用户回答"}
    resume: dict[str, Any] | None = None


def get_chat_service(
    uow: UowDep,
    context: RequestContextDep,
    principal: UserAuthDep,
) -> ChatService:
    return ChatService(
        uow=uow, context=context, principal=principal, runner_factory=build_runner,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def _parse_conversation_id(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


@router.post("/{application_id}/run/stream")
async def run_agent_stream(
    application_id: UUID,
    payload: RunStreamRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    """SSE 流式 chat：依次推送 run_start / llm_start / llm_end / tool_start / tool_end / result / error / final。"""
    conversation_id = _parse_conversation_id(payload.conversation_id)
    history = [h.model_dump() for h in (payload.history or [])]

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event_name, data in service.run_agent_stream(
                application_id=application_id,
                query=payload.query,
                conversation_id=conversation_id,
                history=history,
            ):
                await queue.put(sse_event(event_name, data))
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat producer failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": "chat_failed"}))
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
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{application_id}/run")
async def run_agent(
    application_id: UUID,
    payload: RunStreamRequest,
    service: ChatServiceDep,
) -> dict:
    """非流式 chat：跑完整轮 ReAct 后返回 result 数据。"""
    conversation_id = _parse_conversation_id(payload.conversation_id)
    history = [h.model_dump() for h in (payload.history or [])]

    result: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    async for event_name, data in service.run_agent_stream(
        application_id=application_id,
        query=payload.query,
        conversation_id=conversation_id,
        history=history,
    ):
        if event_name == "result":
            result = data
        elif event_name == "error":
            error = data
    if error is not None and not result:
        raise AppError(error.get("message", "chat failed"))
    return result or {"content": ""}


@router.post("/{application_id}/chatflow/run/stream")
async def run_chatflow_stream(
    application_id: UUID,
    payload: ChatflowRunRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    """对话流 SSE 运行：推送 run_start / node_* / output_message / question / result / final。"""
    # 鉴权、参数组合、会话/线程归属必须在返回 StreamingResponse 之前校验，
    # 这些错误走 JSON 4xx，而不是 SSE error 事件。
    prepared = service.prepare_chatflow_run(
        application_id,
        message=payload.message,
        conversation_id=payload.conversation_id,
        resume=payload.resume,
        thread_id=payload.thread_id,
    )
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event_name, data in service.run_chatflow_stream(
                prepared,
                inputs=payload.inputs,
            ):
                await queue.put(sse_event(event_name, data))
        except Exception as exc:  # noqa: BLE001
            logger.exception("chatflow producer failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": "chatflow_failed"}))
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
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{application_id}/workflow/run")
async def run_workflow(
    application_id: UUID,
    payload: WorkflowRunRequest,
    service: ChatServiceDep,
) -> dict:
    """workflow 非流式运行：返回 {status, output, thread_id, run_id}。"""
    return await service.run_workflow(
        application_id=application_id,
        inputs=payload.inputs,
        thread_id=payload.thread_id,
        conversation_id=payload.conversation_id,
    )


@router.get("/{application_id}/conversations")
async def list_conversations(
    application_id: UUID,
    service: ChatServiceDep,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """列出当前用户在指定应用下的会话列表（按 updated_at 倒序）。"""
    return await service.list_conversations(
        application_id=application_id, limit=limit, offset=offset,
    )


@router.get("/{application_id}/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    application_id: UUID,
    conversation_id: UUID,
    service: ChatServiceDep,
    limit: int = 100,
) -> list[dict]:
    """拉取某会话的历史消息（升序），用于前端恢复聊天上下文。"""
    return await service.list_messages(
        application_id=application_id,
        conversation_id=conversation_id,
        limit=limit,
    )
