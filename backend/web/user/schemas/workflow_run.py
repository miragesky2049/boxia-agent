"""用户端工作流运行请求/响应模型。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowRunRequest(BaseModel):
    """运行一次工作流的请求体；inputs 对齐 graph.variables。"""

    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowNodeStateOut(BaseModel):
    """单个节点的运行状态。"""

    node_id: str
    type: str
    status: str
    duration_ms: int = 0
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkflowRunResponse(BaseModel):
    """运行结果。"""

    workflow_id: UUID
    run_id: str
    outputs: dict[str, Any]
    node_states: list[WorkflowNodeStateOut]
    usage: dict[str, int]
    finish_reason: str
