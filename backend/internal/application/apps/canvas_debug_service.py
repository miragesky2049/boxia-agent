"""画布试运行应用服务：invoke / resume 编排与事件流（DDD 五期从 apps_admin router 下沉）。

对齐 chat_service.run_chatflow_stream 的模式：本服务产出 (event_name, payload) 元组流，
路由层只做 sse_event 帧格式化 + StreamingResponse。GraphRuntime 装配经
CanvasDebugRuntimeFactory 端口由组合根注入，应用层不 import web / infra。

事件契约（与迁移前 router 完全一致）：
run_start → node_start/node_end...（穿插）→ result | question | interrupted | error
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from internal.application.apps.ports import CanvasDebugRuntimeFactory
from internal.application.errors import AppError, ValidationError
from internal.domain.graph.runtime import GraphInterrupted

logger = logging.getLogger(__name__)

NodeEventAction = Callable[[Any], Awaitable[Any]]


class CanvasDebugService:
    """admin 画布试运行编排：节点数护栏、run_start/中断映射、队列泵。"""

    # 画布试运行的节点规模上限（与迁移前 router 常量一致）
    MAX_DEBUG_NODES = 50

    def __init__(self, runtime_factory: CanvasDebugRuntimeFactory) -> None:
        self._runtime_factory = runtime_factory

    async def open_run(
        self,
        *,
        graph: dict[str, Any],
        inputs: dict[str, Any] | None,
        application_id: UUID,
        variables_application_id: UUID | None,
        conversation_id: UUID | None,
        thread_id: str | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """全图试运行：装配 runtime 后立即返回事件流（校验错误在流外抛出，与迁移前一致）。"""

        async def _action(runtime: Any) -> Any:
            return await runtime.invoke(inputs)

        return await self._start(
            graph=graph,
            application_id=application_id,
            variables_application_id=variables_application_id,
            run_id=uuid4(),
            conversation_id=conversation_id,
            thread_id=thread_id,
            action=_action,
        )

    async def open_resume(
        self,
        *,
        graph: dict[str, Any],
        resume_value: dict[str, Any],
        run_id: UUID,
        application_id: UUID,
        variables_application_id: UUID | None,
        conversation_id: UUID | None,
        thread_id: str | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """人审 / 问答续跑：从 interrupt 点以 Command(resume=...) 继续。"""

        async def _action(runtime: Any) -> Any:
            return await runtime.resume(resume_value)

        return await self._start(
            graph=graph,
            application_id=application_id,
            variables_application_id=variables_application_id,
            run_id=run_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            action=_action,
        )

    async def _start(
        self,
        *,
        graph: dict[str, Any],
        application_id: UUID,
        variables_application_id: UUID | None,
        run_id: UUID,
        conversation_id: UUID | None,
        thread_id: str | None,
        action: NodeEventAction,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        self._validate_graph(graph)
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def emitter(event_type: str, payload: dict[str, Any]) -> None:
            await queue.put((event_type, payload))

        runtime = self._runtime_factory(
            graph=graph,
            application_id=application_id,
            variables_application_id=variables_application_id,
            run_id=run_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            on_node_event=emitter,
        )
        # 与用户端对话流一致：先发 run_start，前端据此拿到 thread/run/conversation
        await queue.put(
            (
                "run_start",
                {
                    "conversation_id": str(runtime.conversation_id)
                    if runtime.conversation_id
                    else None,
                    "thread_id": runtime.thread_id,
                    "run_id": str(runtime.run_id),
                },
            )
        )

        async def runner_task() -> None:
            try:
                output = await action(runtime)
                await queue.put(("result", {"outputs": output}))
            except GraphInterrupted as exc:
                await self._push_interrupt(queue, exc, runtime)
            except AppError as exc:
                await queue.put(("error", {"message": exc.message, "code": exc.status_code}))
            except Exception as exc:  # noqa: BLE001
                logger.exception("debug stream failed")
                await queue.put(("error", {"message": str(exc), "code": 500}))
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner_task())
        return self._pump(queue, task)

    @classmethod
    def _validate_graph(cls, graph: dict[str, Any]) -> None:
        """仅平台管理员可用；节点数上限保护试运行不被滥用。"""
        nodes = graph.get("nodes") or []
        if not isinstance(nodes, list) or len(nodes) > cls.MAX_DEBUG_NODES:
            raise ValidationError("graph 节点数必须在 1-50 之间")

    @staticmethod
    async def _push_interrupt(
        queue: asyncio.Queue[Any],
        exc: GraphInterrupted,
        runtime: Any,
    ) -> None:
        """把中断翻译成事件：问答节点发 question，人审节点发 interrupted。"""
        payload = exc.interrupt_payload or {}
        common = {
            "thread_id": exc.thread_id,
            "run_id": str(runtime.run_id),
            "conversation_id": str(runtime.conversation_id) if runtime.conversation_id else None,
        }
        if payload.get("type") == "question":
            await queue.put(
                (
                    "question",
                    {
                        **common,
                        "node_id": payload.get("node_id"),
                        "node_title": payload.get("node_title"),
                        "question": payload.get("question") or "",
                        "options": payload.get("options") or [],
                    },
                )
            )
        else:
            await queue.put(("interrupted", {**common, "approval": payload}))

    @staticmethod
    async def _pump(
        queue: asyncio.Queue[Any],
        task: asyncio.Task[None],
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """消费队列直到哨兵；客户端断连时取消 runner，防任务泄漏。"""
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
