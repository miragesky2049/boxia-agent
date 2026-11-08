"""用户端 chat / workflow 运行端点。

- POST /agents/{id}/chatflow/run/stream  统一对话 SSE 入口（0074 PRD M3 端点收敛）：
  服务端按应用 flow_type 分派——对话流走图管线，智能体/旧聊天应用走 chat 三通道管线
- POST /agents/{id}/workflow/run   workflow 非流式运行（dag）

历史端点 POST /agents/{id}/run/stream 与 /run 已退役删除：SSE 帧契约由统一入口
完整保留（run_start/llm_*/tool_*/plan/reflect/result/error/final），并新增
interrupted 帧承载 F10 工具审批挂起。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.apps.chat_service import ChatService
from internal.application.apps.memory_service import MemorySummarizerService
from internal.application.errors import ValidationError
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.tasks.memory_tasks import extract_memories
from web.deps.apps_services import (
    make_agent_memory_repository,
    make_app_resource_service,
    make_application_service,
    make_conversation_repository,
    make_message_repository,
    make_model_service,
    make_run_repository,
)
from web.deps.auth import UserAuthDep
from web.deps.db import UowDep
from web.deps.graph import build_runner, make_tool_executor_factory
from web.deps.sse import SSE_HEADERS, sse_event
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["user-chat"])


class HistoryMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = ""


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    # 对话流运行上下文：消息/会话类节点未显式连线会话 ID 时回退使用
    conversation_id: UUID | None = None


class ConversationRunRequest(BaseModel):
    """统一对话入口请求体（chatflow 与 agent/legacy chat 共用）。"""

    # 纯续跑（resume）时允许为空；message 与 resume 至少提供一个是服务层校验
    message: str = Field("", max_length=8000)
    conversation_id: UUID | None = None
    thread_id: str | None = None
    # 对话流启动变量（agent 通道忽略）
    inputs: dict[str, Any] = Field(default_factory=dict)
    # 中断续跑载荷：对话流为 {"answer": 用户回答}；F10 工具审批为
    # {"approved": bool, "comment": str}
    resume: dict[str, Any] | None = None
    # 0074 PRD F8 校准：agent 型前端省略 history 以启用服务端记忆，
    # 旧聊天应用继续携带；None 与 [] 语义区分沿用 M2 约定
    history: list[HistoryMessage] | None = None
    # 0074 PRD F9：随消息携带的图片 URL（节点 visionEnabled 门控）
    images: list[str] = Field(default_factory=list, max_length=8)
    # M4 PRD F14.9：手动归位（结束接管、发言权交回会话归属应用）；true 时不要求
    # message、不发 run，仅清路由态并回一帧 handoff(returned=true)
    handback: bool = False


def get_chat_service(
    uow: UowDep,
    context: RequestContextDep,
    principal: UserAuthDep,
) -> ChatService:
    return ChatService(
        uow=uow,
        context=context,
        principal=principal,
        runner_factory=build_runner,
        app_service=make_application_service(uow),
        model_service=make_model_service(uow.session),
        resource_service=make_app_resource_service(uow),
        conv_repo=make_conversation_repository(uow.session),
        msg_repo=make_message_repository(uow.session),
        run_repo=make_run_repository(uow.session),
        default_llm_model_id=get_settings().llm_model_id,
        tool_executor_factory=make_tool_executor_factory(
            uow.session, principal.tenant_id, principal.user_id
        ),
        # M4 PRD F15：摘要式记忆执行服务（复用同请求的模型与会话仓储）
        memory_summarizer=MemorySummarizerService(
            model_service=make_model_service(uow.session),
            conv_repo=make_conversation_repository(uow.session),
        ),
        # M4 PRD F16.3：轮后长期记忆抽取投递（Celery；broker 不可达由服务侧降级 warning）
        memory_extract_enqueuer=lambda run_id: extract_memories.delay(str(run_id)),
        # M4 PRD F16.4：召回注入仓储（longTerm.enabled 时才查询，关闭态零开销）
        memory_repo=make_agent_memory_repository(uow.session),
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def _sse_response(
    frames: AsyncIterator[tuple[str, dict[str, Any]]],
    error_code: str,
) -> StreamingResponse:
    """SSE 公用泵：服务帧序列 -> SSE 帧；producer 异常统一转 error+final。"""

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event_name, data in frames:
                await queue.put(sse_event(event_name, data))
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话流运行失败 code=%s", error_code)
            await queue.put(sse_event("error", {"message": str(exc), "code": error_code}))
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
            with contextlib.suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{application_id}/chatflow/run/stream")
async def run_conversation_stream(
    application_id: UUID,
    payload: ConversationRunRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    """统一对话 SSE 入口：按应用类型分派对话流 / 智能体 chat 管线。

    鉴权、参数组合、会话/线程归属必须在返回 StreamingResponse 之前校验，
    这些错误走 JSON 4xx，而不是 SSE error 事件。
    """
    app_card = service.resolve_conversation_channel(application_id)

    if app_card.get("flow_type") == "chatflow":
        prepared = service.prepare_chatflow_run(
            application_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            resume=payload.resume,
            thread_id=payload.thread_id,
        )
        return _sse_response(
            service.run_chatflow_stream(prepared, inputs=payload.inputs),
            "chatflow_failed",
        )

    # 0074 PRD M3 端点收敛：agent 与旧 workflow 型聊天应用统一走 chat 三通道管线
    service.prepare_chat_run(
        application_id,
        message=payload.message,
        conversation_id=payload.conversation_id,
        resume=payload.resume,
        handback=payload.handback,
    )
    if payload.handback:
        # M4 PRD F14.9：手动归位不发 run，清路由态 + 通告帧（4xx 校验已在预检收口）
        handback_cid = payload.conversation_id
        if handback_cid is None:
            # 预检已拦截此形态，此处仅类型收窄兜底
            raise ValidationError("handback 必须提供 conversation_id")
        handback_ctx = service.prepare_handback(application_id, handback_cid)
        return _sse_response(
            service.run_handback_stream(
                application_id=application_id,
                conversation_id=handback_cid,
                prepared=handback_ctx,
            ),
            "chat_failed",
        )
    # M4 PRD F14.9：接管路由在 SSE 之前收口（目标不可见 → JSON 4xx，原路由保持不动）
    route_app_id = service.resolve_handoff_application(
        application_id,
        conversation_id=payload.conversation_id,
        resume=payload.resume,
    )
    history = [h.model_dump() for h in payload.history] if payload.history is not None else None
    return _sse_response(
        service.run_agent_stream(
            application_id=application_id,
            query=payload.message,
            conversation_id=payload.conversation_id,
            history=history,
            images=payload.images or None,
            resume=payload.resume,
            thread_id=payload.thread_id,
            route_application_id=route_app_id if route_app_id != application_id else None,
        ),
        "chat_failed",
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
        application_id=application_id,
        limit=limit,
        offset=offset,
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
