"""END 节点：把求值后的入参作为最终输出。"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class EndNodeHandler(NodeHandler):
    type_name = NodeType.END.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        # END 节点的 inputs 已经是求值后的 {name: value}，直接作为 output
        return NodeResult(outputs=dict(ctx.inputs))


register_node_handler(EndNodeHandler())
