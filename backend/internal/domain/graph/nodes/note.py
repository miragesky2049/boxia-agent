"""Note 注释节点（coze type=7）。

画布注释，无执行语义，不参与 graph 路由。handler 直接返回空 outputs。
前端渲染为便签块，仅用于说明。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class NoteNodeHandler(NodeHandler):
    type_name = NodeType.NOTE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(outputs={})


register_node_handler(NoteNodeHandler())
