"""角色请求/响应模型（平台角色 tenant_id 为空）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoleOut(BaseModel):
    """角色信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int | None
    code: str
    name: str
    description: str
    system_role: str
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    """创建角色请求：基础权限固定为只读，不可指定。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)


class RoleUpdateRequest(BaseModel):
    """更新角色请求：基础权限不可修改，只能通过复制角色继承。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class RoleCopyRequest(BaseModel):
    """复制角色请求；未填写描述时沿用源角色描述。"""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
