"""技能、工具、组件与提示词模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResourcePayload(BaseModel):
    """资源公共入参。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    is_enabled: bool = True
    # 资源归属智能体；为空表示尚未纳入任何智能体
    agent_id: UUID | None = Field(default=None)


class ResourceCloneRequest(BaseModel):
    """克隆资源到目标智能体请求。"""

    agent_id: UUID = Field()
    name: str | None = Field(default=None, min_length=1, max_length=100)


class SkillPayload(ResourcePayload):
    """技能入参。"""

    content: str = Field(default="", max_length=50000)
    config: dict[str, Any] = Field(default_factory=dict)


class SkillOut(SkillPayload):
    """技能出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None = None
    is_platform: bool = False
    created_at: datetime
    updated_at: datetime


class ToolPayload(ResourcePayload):
    """工具入参。"""

    type: str = Field(default="http", max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolOut(ToolPayload):
    """工具出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None = None
    is_platform: bool = False
    created_at: datetime
    updated_at: datetime


class ComponentPayload(ResourcePayload):
    """组件入参。"""

    type: str = Field(default="card", max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


class ComponentOut(ComponentPayload):
    """组件出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None = None
    is_platform: bool = False
    created_at: datetime
    updated_at: datetime


class PromptPayload(ResourcePayload):
    """提示词入参。"""

    content: str = Field(default="", max_length=50000)
    variables: list[str] = Field(default_factory=list)
    category: str = Field(default="", max_length=32)


class PromptOut(PromptPayload):
    """提示词出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None = None
    is_platform: bool = False
    created_at: datetime
    updated_at: datetime
