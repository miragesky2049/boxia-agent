"""Batch 节点（coze type=28）：并行执行子图。

与 Loop 的区别：
- Loop 是串行迭代，有 break/continue 语义
- Batch 是并行 map：对输入数组每项并发执行子图，收集所有结果

config 约定：
- inputParameters.input: 待并行的数组
- parallelCount: 并发度（默认 5）

循环体来自 ctx.subgraph。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult, RuntimeEnv
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)

DEFAULT_PARALLEL = 5
MAX_PARALLEL = 32


class BatchNodeHandler(NodeHandler):
    type_name = NodeType.BATCH.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        items = ctx.inputs.get("input")
        if not isinstance(items, list):
            return NodeResult(outputs={"output": [], "error": "batch 输入不是数组"})

        if not items:
            return NodeResult(outputs={"output": [], "count": 0})

        subgraph = ctx.subgraph
        if subgraph is None:
            return NodeResult(outputs={"output": list(items), "count": len(items)})

        parallel = int(ctx.config.get("parallelCount") or DEFAULT_PARALLEL)
        parallel = max(1, min(parallel, MAX_PARALLEL))
        semaphore = asyncio.Semaphore(parallel)

        async def _run_one(index: int, item: Any) -> dict[str, Any]:
            async with semaphore:
                return await self._run_iteration(ctx, subgraph, item, index, len(items))

        results = await asyncio.gather(
            *[_run_one(i, it) for i, it in enumerate(items)],
            return_exceptions=True,
        )

        output_list: list[Any] = []
        errors: list[str] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                errors.append(f"item[{i}]: {r}")
                output_list.append(None)
            else:
                output_list.append(r.get("output", {}))

        return NodeResult(outputs={
            "output": output_list,
            "count": len(output_list),
            "errors": errors,
        })

    async def _run_iteration(
        self,
        ctx: NodeContext,
        subgraph,
        item: Any,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        from internal.domain.graph.compiler import Compiler

        sub_env = RuntimeEnv(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            run_id=ctx.env.run_id,
            thread_id=f"{ctx.env.thread_id}:batch:{index}",
            application_id=ctx.env.application_id,
        )
        compiler = Compiler(services=ctx.services)
        compiled = compiler.compile(subgraph, sub_env, checkpointer=None)

        initial_state = {
            "input": {"item": item, "index": index, "total": total},
            "node_outputs": {},
            "globals": {},
            "env": {
                "tenant_id": str(ctx.env.tenant_id),
                "user_id": str(ctx.env.user_id) if ctx.env.user_id else None,
                "run_id": str(sub_env.run_id),
                "thread_id": sub_env.thread_id,
            },
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": sub_env.thread_id}},
        )


register_node_handler(BatchNodeHandler())
