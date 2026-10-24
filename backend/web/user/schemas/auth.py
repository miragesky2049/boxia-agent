"""用户端登录与身份模型。"""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """最终用户登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """刷新令牌请求。"""

    refresh_token: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    """最终用户信息（不含密码与内部计数字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    tenant_id: int
    role_id: int


class UserProfileOut(UserOut):
    """当前登录用户身份，含角色与基础权限。"""

    role_code: str
    role_name: str
    permissions: list[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    """登录/刷新响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserOut
