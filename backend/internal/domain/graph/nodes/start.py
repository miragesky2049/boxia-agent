"""START 节点：把工作流入参原样写入 node_outputs。"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class StartNodeHandler(NodeHandler):
    type_name = NodeType.START.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        # START 节点的 output 就是工作流入参本身
        # 注意：ctx.inputs 是空的（START 没有 inputParameters），
        # 真正的入参在 state.input 里，由 Compiler 在构造 ctx 时传入
        # 但我们这里直接用 ctx.inputs 的来源——Compiler 会把 state.input 作为 inputs 传入
        # 所以这里直接返回 inputs 即可
        return NodeResult(outputs=dict(ctx.inputs))


register_node_handler(StartNodeHandler())
