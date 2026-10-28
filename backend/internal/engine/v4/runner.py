"""v4 运行时：编译并执行 graph，记录运行实例，支持人审 interrupt / resume。"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable
from uuid import UUID

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from internal.engine.v4.compiler import compile_graph, infer_runtime_mode
from internal.engine.v4.events import NodeExecutionEvent, publish
from internal.engine.v4.nodes.builtin import (
    ModelResolverCtx,
    SubgraphLoaderCtx,
    ToolResolverCtx,
)

logger = logging.getLogger(__name__)

# 模型解析器签名：(model_id: str) -> LLMClient
ModelResolver = Callable[[str], Any]

# 子图加载器签名：(application_id: str) -> dict（返回 graph JSON，已按 tenant 应用 effective config）
SubgraphLoader = Callable[[str], dict]

# tool 资源解析器签名：(resource_id: str) -> dict | None
ToolResolver = Callable[[str], Any]

# 进程内 checkpointer：按 thread_id 保存图状态，支持 interrupt / resume
# 首期用 MemorySaver（进程内），后续可换 PostgresSaver 持久化
_CHECKPOINTER = MemorySaver()


class GraphInterrupted(Exception):
    """图执行被人审 interrupt 暂停。"""
    def __init__(self, interrupt_payload: dict[str, Any]):
        self.interrupt_payload = interrupt_payload
        super().__init__("图执行被人审节点暂停")


class GraphRunner:
    """编译并执行 graph，返回最终输出，支持人审暂停恢复。"""

    def __init__(
        self,
        graph: dict[str, Any],
        tenant_id: UUID | None = None,
        application_id: UUID | None = None,
        model_resolver: ModelResolver | None = None,
        subgraph_loader: SubgraphLoader | None = None,
        tool_resolver: ToolResolver | None = None,
        thread_id: str | None = None,
    ):
        self.graph = graph
        self.tenant_id = tenant_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
        self.application_id = application_id or uuid.uuid4()
        self.runtime_mode = infer_runtime_mode(graph)
        self.thread_id = thread_id or str(uuid.uuid4())
        self.run_id = uuid.uuid4()
        self._model_resolver = model_resolver
        self._subgraph_loader = subgraph_loader
        self._tool_resolver = tool_resolver
        # 编译时挂 checkpointer，支持 interrupt 暂停
        self.compiled = compile_graph(graph, checkpointer=_CHECKPOINTER)

    def _config(self) -> dict[str, Any]:
        # 按 tenant_id 命名空间隔离 thread_id，防止跨租户通过伪造 thread_id 访问他人 checkpoint
        return {"configurable": {"thread_id": f"{self.tenant_id}:{self.thread_id}"}}

    def _extract_interrupt(self) -> dict[str, Any] | None:
        """从 checkpointer 中取出当前等待的人审 interrupt payload。"""
        state = self.compiled.get_state(self._config())
        if not state.next:
            return None
        for task in state.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                return task.interrupts[0].value
        return None

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行 graph。如果遇到人审 interrupt，抛 GraphInterrupted。"""
        started_at = time.time()
        logger.info(
            f"开始运行: run={self.run_id} thread={self.thread_id} mode={self.runtime_mode} "
            f"nodes={len(self.graph.get('nodes', []))}"
        )

        publish(NodeExecutionEvent(
            run_id=self.run_id,
            tenant_id=self.tenant_id,
            application_id=self.application_id,
            node_id="__run__",
            node_type="run",
            status="started",
            input=input_data,
        ))

        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None

        try:
            await self.compiled.ainvoke(
                {"input": input_data},
                config=self._config(),
            )
            # 检查是否被 interrupt 暂停
            interrupt_payload = self._extract_interrupt()
            if interrupt_payload is not None:
                logger.info(f"运行被人审暂停: thread={self.thread_id}")
                raise GraphInterrupted(interrupt_payload)

            result = await self.compiled.aget_state(self._config())
            output = result.values.get("output", {}) if result.values else {}
            duration_ms = int((time.time() - started_at) * 1000)

            publish(NodeExecutionEvent(
                run_id=self.run_id,
                tenant_id=self.tenant_id,
                application_id=self.application_id,
                node_id="__run__",
                node_type="run",
                status="success",
                output=output,
                duration_ms=duration_ms,
            ))
            logger.info(f"运行完成: run={self.run_id} duration={duration_ms}ms")
            return output

        except GraphInterrupted:
            raise
        except Exception as e:
            duration_ms = int((time.time() - started_at) * 1000)
            publish(NodeExecutionEvent(
                run_id=self.run_id,
                tenant_id=self.tenant_id,
                application_id=self.application_id,
                node_id="__run__",
                node_type="run",
                status="error",
                error=str(e),
                duration_ms=duration_ms,
            ))
            logger.error(f"运行失败: run={self.run_id} error={e}")
            raise
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)

    async def resume(self, approval: dict[str, Any]) -> dict[str, Any]:
        """人审通过后恢复执行。approval 形如 {"approved": true, "comment": "..."}。"""
        started_at = time.time()
        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None

        try:
            await self.compiled.ainvoke(
                Command(resume=approval),
                config=self._config(),
            )
            # 检查是否还有下一个 interrupt
            interrupt_payload = self._extract_interrupt()
            if interrupt_payload is not None:
                raise GraphInterrupted(interrupt_payload)

            result = await self.compiled.aget_state(self._config())
            output = result.values.get("output", {}) if result.values else {}
            duration_ms = int((time.time() - started_at) * 1000)
            logger.info(f"恢复运行完成: thread={self.thread_id} duration={duration_ms}ms")
            return output
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)

    def get_interrupt_state(self) -> dict[str, Any] | None:
        """查询当前 thread 是否在等人审。"""
        return self._extract_interrupt()
