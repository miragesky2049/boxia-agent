"""租户角色请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoleOut(BaseModel):
    """角色信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    code: str
    name: str
    description: str
    system_role: str
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    """创建角色请求。"""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    system_role: str = Field(default="viewer", max_length=16)


class RoleUpdateRequest(BaseModel):
    """更新角色请求。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    system_role: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None
