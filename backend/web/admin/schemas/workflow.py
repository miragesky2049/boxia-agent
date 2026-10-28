"""工作流与模板的请求/响应模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowPayload(BaseModel):
    """工作流入参。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    graph: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    visibility_mode: str = Field(default="all", pattern="^(all|custom)$")


class WorkflowSummaryOut(BaseModel):
    """工作流列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    is_enabled: bool
    visibility_mode: str
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowOut(WorkflowSummaryOut):
    """工作流详情（含 graph）。"""

    graph: dict[str, Any]


class GraphValidateOut(BaseModel):
    """图校验结果。"""

    valid: bool
    node_count: int
    edge_count: int
    node_types: list[str]


class WorkflowClonePayload(BaseModel):
    """从模板克隆工作流入参。"""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class WorkflowTemplatePayload(BaseModel):
    """模板入参（仅产品级）。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    graph: dict[str, Any] = Field(default_factory=dict)
    category: str = Field(default="", max_length=32)
    is_enabled: bool = True


class WorkflowTemplateOut(BaseModel):
    """模板响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    graph: dict[str, Any]
    category: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
