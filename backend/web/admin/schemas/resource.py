"""工具模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResourcePayload(BaseModel):
    """资源公共入参。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    is_enabled: bool = True


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
