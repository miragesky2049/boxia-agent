"""最终用户请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """最终用户信息（不含密码哈希）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    username: str
    display_name: str
    is_active: bool
    role_id: int
    role_ids: list[int] = []
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(BaseModel):
    """创建最终用户请求。"""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=64)
    role_ids: list[int] = Field(min_length=1)
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    """更新最终用户请求。"""

    display_name: str | None = Field(default=None, max_length=64)
    role_ids: list[int] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class UserResetPasswordRequest(BaseModel):
    """重置最终用户密码请求。"""

    new_password: str = Field(min_length=1, max_length=128)
