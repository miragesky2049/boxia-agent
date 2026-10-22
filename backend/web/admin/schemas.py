"""管理端通用请求/响应模型。"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminUserOut(BaseModel):
    """管理员信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class LoginResponse(BaseModel):
    """登录/刷新响应：短期访问令牌 + 可轮换刷新令牌。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: AdminUserOut


class RefreshRequest(BaseModel):
    """刷新令牌请求。"""

    refresh_token: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    """修改密码请求。"""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminUserCreateRequest(BaseModel):
    """创建管理员请求。"""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(default="admin", max_length=16)


class AdminUserUpdateRequest(BaseModel):
    """调整管理员请求。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None


class AdminUserResetPasswordRequest(BaseModel):
    """重置管理员密码请求。"""

    new_password: str = Field(min_length=12, max_length=128)


class AuditLogOut(BaseModel):
    """审计日志出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    actor_username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    request_id: str | None
    ip: str | None
    user_agent: str | None
    detail: dict[str, Any]
    created_at: datetime


class PageOut(BaseModel, Generic[T]):
    """分页响应。"""

    items: list[T]
    total: int
    page: int
    page_size: int


class ResourcePayload(BaseModel):
    """资源公共入参。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    is_enabled: bool = True


class SkillPayload(ResourcePayload):
    """技能入参。"""

    content: str = Field(default="", max_length=50000)
    config: dict[str, Any] = Field(default_factory=dict)


class SkillOut(SkillPayload):
    """技能出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ToolPayload(ResourcePayload):
    """工具入参。"""

    type: str = Field(default="http", max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolOut(ToolPayload):
    """工具出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ComponentPayload(ResourcePayload):
    """组件入参。"""

    type: str = Field(default="card", max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


class ComponentOut(ComponentPayload):
    """组件出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
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

    id: int
    created_at: datetime
    updated_at: datetime
