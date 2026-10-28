"""v4 运行时：编译并执行 graph，记录运行实例。"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable
from uuid import UUID

from internal.engine.v4.compiler import compile_graph, infer_runtime_mode
from internal.engine.v4.events import NodeExecutionEvent, publish
from internal.engine.v4.nodes.builtin import ModelResolverCtx

logger = logging.getLogger(__name__)

# 模型解析器签名：(model_id: str) -> LLMClient
ModelResolver = Callable[[str], Any]


class GraphRunner:
    """编译并执行 graph，返回最终输出，记录运行实例。"""

    def __init__(
        self,
        graph: dict[str, Any],
        tenant_id: UUID | None = None,
        application_id: UUID | None = None,
        model_resolver: ModelResolver | None = None,
    ):
        self.graph = graph
        self.tenant_id = tenant_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
        self.application_id = application_id or uuid.uuid4()
        self.runtime_mode = infer_runtime_mode(graph)
        self.compiled = compile_graph(graph)
        self.run_id = uuid.uuid4()
        self.langgraph_thread_id = str(uuid.uuid4())
        self._model_resolver = model_resolver

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行 graph，返回 end 节点的输出。"""
        started_at = time.time()
        logger.info(
            f"开始运行: run={self.run_id} mode={self.runtime_mode} "
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

        # 通过 contextvar 注入模型解析器，节点在同一 asyncio 上下文内可见
        token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None

        try:
            result = await self.compiled.ainvoke(
                {"input": input_data},
                config={"configurable": {"thread_id": self.langgraph_thread_id}},
            )
            output = result.get("output", {})
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
            if token is not None:
                ModelResolverCtx.reset(token)
