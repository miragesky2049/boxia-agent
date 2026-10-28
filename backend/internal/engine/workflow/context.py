"""Workflow 运行期上下文：贯穿节点执行、变量插值与租户透传。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from internal.domain.repository.protocols import UnitOfWork
from internal.engine.context import AgentRunContext


@dataclass
class WorkflowContext:
    """一次工作流运行的上下文。

    - ``global_inputs``：用户传入的入参，与 graph.variables 对齐；start 节点直接返回。
    - ``node_outputs``：每个节点执行后写入 ``{node_id: {field: value}}``，供下游插值。
    - ``run_context``：复用 AgentRunContext 的租户 / 用户 / run_id 透传能力。
    - ``uow``：ToolNode 用它从 tools 表加载工具实体；LLMNode 不用。
    """

    workflow_id: UUID
    tenant_id: UUID
    user_id: UUID | None
    global_inputs: dict[str, Any]
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    uow: UnitOfWork | None = None
    run_id: str = field(default_factory=lambda: f"wf_{uuid4().hex[:24]}")

    def as_agent_context(self) -> AgentRunContext:
        """构造兼容 AgentRunContext 的对象，供 LLM / Tool 透传 header。"""
        return AgentRunContext(
            agent_id=self.workflow_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            conversation_id=self.run_id,
            run_id=self.run_id,
        )

    def record_output(self, node_id: str, output: dict[str, Any]) -> None:
        """节点执行完成后由 executor 写入输出，供下游节点插值。"""
        self.node_outputs[node_id] = output
