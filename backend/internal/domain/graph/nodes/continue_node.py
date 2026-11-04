"""Continue 节点（coze type=29）：循环体内跳过本次迭代。

本身不执行业务逻辑，只产出一个 __continue__ 标记，由外层 Loop 节点检测后跳过本次结果。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class ContinueNodeHandler(NodeHandler):
    type_name = NodeType.CONTINUE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(outputs={"__continue__": True})


register_node_handler(ContinueNodeHandler())
