"""Loop 节点（coze type=21）：循环执行子图。

config 约定（来自 coze inputs）：
- loopType: "array" / "count" / "condition"
- loopCount: 循环次数（count 类型时）
- inputParameters: 循环输入（array 类型时是数组）

循环体子图来自 ctx.subgraph（convert 阶段从 blocks/edges 翻译）。

运行时逻辑：
1. 解析循环输入（数组或计数）
2. 逐次迭代：把当前 item/index 注入子图 START，编译并执行子图
3. 检测循环体内的 Break(type=19) / Continue(type=29) 节点输出
4. 收集每次迭代 END 节点的 outputs，组成最终 output 数组
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult, RuntimeEnv
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)

# 单次迭代最多执行次数上限，防止死循环
MAX_ITERATIONS = 1000


class LoopNodeHandler(NodeHandler):
    type_name = NodeType.LOOP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        loop_type = str(config.get("loopType") or "array")

        items = self._resolve_items(ctx, loop_type)
        max_iterations = len(items)
        if max_iterations > MAX_ITERATIONS:
            return NodeResult(outputs={"error": f"循环次数超过上限 {MAX_ITERATIONS}"})

        subgraph = ctx.subgraph
        if subgraph is None:
            # 没有循环体，退化为直接返回输入数组
            return NodeResult(outputs={"output": list(items), "count": max_iterations})

        accumulated: list[Any] = []
        broke = False

        for index, item in enumerate(items):
            iter_output = await self._run_one_iteration(ctx, subgraph, item, index, max_iterations)

            node_outputs = iter_output.get("node_outputs", {})
            if self._has_break(node_outputs):
                broke = True
                break
            if self._has_continue(node_outputs):
                continue

            iter_result = iter_output.get("output", {})
            accumulated.append(iter_result)

        return NodeResult(outputs={
            "output": accumulated,
            "count": max_iterations,
            "index": max_iterations if broke else max_iterations - 1,
        })

    def _resolve_items(self, ctx: NodeContext, loop_type: str) -> list[Any]:
        loop_input = ctx.inputs.get("input")
        if loop_type == "array":
            if not isinstance(loop_input, list):
                return []
            return list(loop_input)
        # count 类型
        max_count = int(ctx.config.get("loopCount", 10) or 10)
        return list(range(max_count))

    async def _run_one_iteration(
        self,
        ctx: NodeContext,
        subgraph,
        item: Any,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        """执行单次迭代：编译子图并 ainvoke。"""
        # 延迟导入避免循环依赖
        from internal.domain.graph.compiler import Compiler

        sub_env = RuntimeEnv(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            run_id=ctx.env.run_id,
            thread_id=f"{ctx.env.thread_id}:loop:{index}",
            application_id=ctx.env.application_id,
        )
        sub_compiler = Compiler(services=ctx.services)
        compiled = sub_compiler.compile(subgraph, sub_env, checkpointer=None)

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
