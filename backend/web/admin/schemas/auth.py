"""登录、令牌与管理员账号模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    role_id: int | None = None
    role_code: str = ""
    role_name: str = ""
    is_active: bool
    must_change_password: bool
    tenant_id: int | None = None
    is_platform: bool = False
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
    # 长度策略由 Settings 在服务层统一校验，避免请求模型与配置各写一份
    new_password: str = Field(min_length=1, max_length=128)


class AdminUserCreateRequest(BaseModel):
    """创建管理员请求；必须绑定具备管理端访问权限的角色。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role_id: int = Field(ge=1)


class AdminUserUpdateRequest(BaseModel):
    """调整管理员请求。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role_id: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class AdminUserResetPasswordRequest(BaseModel):
    """重置管理员密码请求。"""

    new_password: str = Field(min_length=1, max_length=128)
