"""VariableMerge 节点（coze type=32）：并行分支汇合。

langgraph 天然支持并行分支汇合（多条边指向同一节点时，等所有上游完成后才触发）。
本节点 handler 只做透传：compiler 在求值 inputs 时已经把所有上游分支的 outputs
解析成具体值，这里直接原样吐出去即可。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class VariableMergeNodeHandler(NodeHandler):
    type_name = NodeType.VARIABLE_MERGE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(outputs=dict(ctx.inputs))


register_node_handler(VariableMergeNodeHandler())
