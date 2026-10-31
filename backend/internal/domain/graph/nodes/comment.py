"""Comment 便签节点（coze type=31）。

画布便签，无执行语义，不参与 graph 路由。handler 直接返回空 outputs。
前端渲染为黄色便签块，仅用于注释说明。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class CommentNodeHandler(NodeHandler):
    type_name = NodeType.COMMENT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(outputs={})


register_node_handler(CommentNodeHandler())
