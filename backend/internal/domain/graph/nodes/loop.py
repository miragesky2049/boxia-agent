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
        """并发执行：手动 create_task + as_completed，支持 break/continue 语义。

        - break：任一迭代产出 __break__ 后，取消其余尚未启动/正在运行的任务；
          触发 break 的那次迭代本身不写入结果（与串行一致）。
        - continue：产出 __continue__ 的迭代跳过输出，其余迭代不受影响。
        - 结果按原数组下标排序，保证输出顺序与输入顺序对齐。
        """
        semaphore = asyncio.Semaphore(MAX_PARALLELISM)
        results: dict[int, Any] = {}
        break_received = False

        async def _guarded(item: Any, index: int) -> tuple[int, dict[str, Any] | None, bool, bool]:
            async with semaphore:
                if break_received:
                    return index, None, False, False
                try:
                    iter_output = await self._invoke_once(ctx, compiled, item, index, total)
                except asyncio.CancelledError:
                    raise
                node_outputs = iter_output.get("node_outputs", {})
                is_break = self._has_break(node_outputs)
                is_continue = self._has_continue(node_outputs)
                return index, iter_output.get("output", {}), is_break, is_continue

        tasks = [asyncio.create_task(_guarded(item, i)) for i, item in enumerate(items)]
        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    index, output, is_break, is_continue = await fut
                except asyncio.CancelledError:
                    continue
                if is_break:
                    break_received = True
                    # 与串行语义一致：break 只保留该迭代之前的结果。事件循环繁忙时
                    # 靠后下标的迭代可能先于 break 帧被 as_completed 处理/完成，
                    # 此处按触发下标截断，避免 break 想停止的输出泄漏进结果。
                    results = {i: v for i, v in results.items() if i < index}
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    continue
                if is_continue:
                    continue
                if output is not None and not break_received:
                    results[index] = output
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        return [results[i] for i in sorted(results)]

    async def _invoke_once(
        self,
        ctx: NodeContext,
        compiled,
        item: Any,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        """执行单次迭代。

        A13：子迭代 checkpointer thread_id 必须带租户前缀，避免与主图 checkpoint key 错位。
        业务裸 thread_id = `{父thread_id}:loop:{index}`；checkpoint key = `{tenant}:{业务裸thread_id}`。
        """
        sub_thread_id = f"{ctx.env.thread_id}:loop:{index}"
        checkpoint_thread_id = f"{ctx.env.tenant_id}:{sub_thread_id}"
        initial_state = {
            "input": {"item": item, "index": index, "total": total},
            "node_outputs": {},
            "globals": {},
            "env": {
                "tenant_id": str(ctx.env.tenant_id),
                "user_id": str(ctx.env.user_id) if ctx.env.user_id else None,
                "run_id": str(ctx.env.run_id),
                "thread_id": sub_thread_id,
            },
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": checkpoint_thread_id}},
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
