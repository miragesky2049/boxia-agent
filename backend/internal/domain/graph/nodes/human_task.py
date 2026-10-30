"""人审节点（coze type=60）：stub。

后续迭代要实现：
- langgraph.types.interrupt({type:"human_approval", assignee_role, instructions, snapshot})
- Runtime 从 aget_state().tasks[].interrupts[0].value 取出 payload
- 抛 GraphInterrupted 给上层
- resume(approval) 用 Command(resume=approval) 继续
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class HumanTaskNodeHandler(NodeHandler):
    type_name = NodeType.HUMAN_APPROVAL.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        raise NotImplementedError(
            "human_task 人审节点尚未实现，后续迭代接入 langgraph interrupt + Command(resume)"
        )


register_node_handler(HumanTaskNodeHandler())
