"""Loop 节点（coze type=21）：循环执行子图。

config 约定（来自 coze inputs）：
- loopType: "array" / "count" / "condition"
- loopCount: 循环次数（count 类型时）
- parallel: bool，是否并发执行（默认 false 串行；并发时 break/continue 不生效）

运行时逻辑：
1. 解析循环输入（数组或计数）
2. 编译子图一次，缓存 compiled 对象（避免每次迭代重复编译）
3. 串行或并发执行每次迭代
4. 收集每次迭代 END 节点的 outputs，组成最终 output 数组
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult, RuntimeEnv
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)

# 单次迭代最多执行次数上限，防止死循环
MAX_ITERATIONS = 1000
# 并发模式下最大并行度
MAX_PARALLELISM = 10


class LoopNodeHandler(NodeHandler):
    type_name = NodeType.LOOP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        loop_type = str(config.get("loopType") or "array")
        parallel = bool(config.get("parallel", False))

        items = self._resolve_items(ctx, loop_type)
        max_iterations = len(items)
        if max_iterations > MAX_ITERATIONS:
            return NodeResult(outputs={"error": f"循环次数超过上限 {MAX_ITERATIONS}"})

        subgraph = ctx.subgraph
        if subgraph is None:
            return NodeResult(outputs={"output": list(items), "count": max_iterations})

        # 编译子图一次，缓存给所有迭代复用
        compiled = self._compile_subgraph(ctx, subgraph)

        if parallel:
            accumulated = await self._run_parallel(ctx, compiled, items, max_iterations)
        else:
            accumulated = await self._run_serial(ctx, compiled, items, max_iterations)

        return NodeResult(outputs={
            "output": accumulated,
            "count": max_iterations,
            "index": len(accumulated) - 1,
        })

    def _resolve_items(self, ctx: NodeContext, loop_type: str) -> list[Any]:
        loop_input = ctx.inputs.get("input")
        if loop_type == "array":
            if not isinstance(loop_input, list):
                return []
            return list(loop_input)
        max_count = int(ctx.config.get("loopCount", 10) or 10)
        return list(range(max_count))

    def _compile_subgraph(self, ctx: NodeContext, subgraph):
        """编译子图一次，所有迭代复用。"""
        from internal.domain.graph.compiler import Compiler

        sub_env = RuntimeEnv(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            run_id=ctx.env.run_id,
            thread_id=ctx.env.thread_id,
            application_id=ctx.env.application_id,
        )
        compiler = Compiler(services=ctx.services)
        return compiler.compile(subgraph, sub_env, checkpointer=None)

    async def _run_serial(
        self,
        ctx: NodeContext,
        compiled,
        items: list[Any],
        total: int,
    ) -> list[Any]:
        """串行执行：支持 break/continue 语义。"""
        accumulated: list[Any] = []
        for index, item in enumerate(items):
            iter_output = await self._invoke_once(ctx, compiled, item, index, total)

            node_outputs = iter_output.get("node_outputs", {})
            if self._has_break(node_outputs):
                break
            if self._has_continue(node_outputs):
                continue

            accumulated.append(iter_output.get("output", {}))
        return accumulated

    async def _run_parallel(
        self,
        ctx: NodeContext,
        compiled,
        items: list[Any],
        total: int,
    ) -> list[Any]:
        """并发执行：用 asyncio.gather，最多 MAX_PARALLELISM 并发。

        注意：并发模式下 break/continue 不生效（所有迭代都已启动）。
        单个迭代失败会抛异常，导致整个 Loop 失败（可由 ErrorPolicy 降级）。
        """
        semaphore = asyncio.Semaphore(MAX_PARALLELISM)

        async def _guarded(item: Any, index: int) -> Any:
            async with semaphore:
                iter_output = await self._invoke_once(ctx, compiled, item, index, total)
                return iter_output.get("output", {})

        tasks = [_guarded(item, i) for i, item in enumerate(items)]
        return await asyncio.gather(*tasks)

    async def _invoke_once(
        self,
        ctx: NodeContext,
        compiled,
        item: Any,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        """执行单次迭代。"""
        initial_state = {
            "input": {"item": item, "index": index, "total": total},
            "node_outputs": {},
            "globals": {},
            "env": {
                "tenant_id": str(ctx.env.tenant_id),
                "user_id": str(ctx.env.user_id) if ctx.env.user_id else None,
                "run_id": str(ctx.env.run_id),
                "thread_id": f"{ctx.env.thread_id}:loop:{index}",
            },
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": f"{ctx.env.thread_id}:loop:{index}"}},
        )

    def _has_break(self, node_outputs: dict[str, dict[str, Any]]) -> bool:
        for out in node_outputs.values():
            if out.get("__break__"):
                return True
        return False

    def _has_continue(self, node_outputs: dict[str, dict[str, Any]]) -> bool:
        for out in node_outputs.values():
            if out.get("__continue__"):
                return True
        return False


register_node_handler(LoopNodeHandler())
