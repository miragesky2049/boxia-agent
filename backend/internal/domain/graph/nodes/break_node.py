"""Break 节点（coze type=19）：循环体内跳出当前循环。

本身不执行业务逻辑，只产出一个 __break__ 标记，由外层 Loop 节点检测后停止迭代。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class BreakNodeHandler(NodeHandler):
    type_name = NodeType.BREAK.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(outputs={"__break__": True})


register_node_handler(BreakNodeHandler())
