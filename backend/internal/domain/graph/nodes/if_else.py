"""IF 条件分支节点（coze type=8）。

coze 的 IF 节点 config 里有 conditions / cases 结构。
本 handler 只负责计算 route（出口端口名），实际路由由 Compiler 的 conditional_edges 处理。

阶段 1 简化：先支持单条件布尔求值，后续扩展多 case。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class IfElseNodeHandler(NodeHandler):
    type_name = NodeType.IF.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        # 阶段 1：inputs 里已经有求值后的条件字段
        # coze 的 IF 节点出口端口名通常是 "true" / "false" 或 case id
        # 这里简化：只要 inputs 非空且不为 False 就走 true
        condition_value = ctx.inputs.get("condition")
        matched = bool(condition_value)

        return NodeResult(
            outputs={"condition": condition_value},
            route="true" if matched else "false",
        )


register_node_handler(IfElseNodeHandler())
