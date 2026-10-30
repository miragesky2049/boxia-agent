"""人审节点（coze type=60）：langgraph interrupt 中断 + Command(resume) 续跑。

运行流程：
1. 节点第一次执行时调用 interrupt({assignee_role, instructions, snapshot})，
   langgraph 把当前 state 持久化到 checkpointer，然后抛出 GraphInterrupted
2. Runtime 捕获 GraphInterrupted，返回中断 payload 给调用方
3. 调用方审批后，用同一个 thread_id + Command(resume={approved: bool, comment}) 重新执行
4. 节点从 interrupt() 拿到 resume 值，继续执行：批准则返回 outputs，拒绝则抛异常

依赖：
- checkpointer 必须开启（AsyncPostgresSaver），否则 interrupt 无法持久化
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class HumanTaskNodeHandler(NodeHandler):
    type_name = NodeType.HUMAN_APPROVAL.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}

        # 构造中断 payload：审批人需要看到的上下文
        payload: dict[str, Any] = {
            "type": "human_approval",
            "node_id": ctx.node_id,
            "node_title": str(config.get("title") or "人审节点"),
            "assignee_role": str(config.get("assignee_role") or ""),
            "instructions": str(config.get("instructions") or ""),
            "snapshot": dict(ctx.inputs),
        }

        # 第一次执行：抛出 interrupt，langgraph 持久化 state 后返回 GraphInterrupted
        # 第二次执行（resume）：interrupt() 返回 Command 的 resume 值
        resume_value: dict[str, Any] = interrupt(payload) or {}

        approved = bool(resume_value.get("approved", False))
        comment = str(resume_value.get("comment") or "")

        if not approved:
            # 审批拒绝：抛异常让流程失败（或按 ErrorPolicy 降级）
            raise RuntimeError(f"人审被拒绝: {comment or '无备注'}")

        # 批准：把审批结果作为输出，继续往下走
        return NodeResult(
            outputs={
                "approved": True,
                "comment": comment,
                "approved_by": str(resume_value.get("approver") or ""),
            }
        )


register_node_handler(HumanTaskNodeHandler())
