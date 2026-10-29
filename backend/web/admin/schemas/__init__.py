"""管理端请求/响应模型统一出口。"""

from web.admin.schemas.audit import AuditLogOut
from web.admin.schemas.auth import (
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserResetPasswordRequest,
    AdminUserUpdateRequest,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
)
from web.admin.schemas.common import PageOut
from web.admin.schemas.context import AdminContextOut, PublicContextOut
from web.admin.schemas.resource import (
    ComponentOut,
    ComponentPayload,
    PromptOut,
    PromptPayload,
    ResourcePayload,
    SkillOut,
    SkillPayload,
    ToolOut,
    ToolPayload,
)
from web.admin.schemas.tenant import (
    AppEnv,
    PasswordPolicyOut,
    TenantCreateRequest,
    TenantOut,
    TenantResolution,
    TenantSwitchMode,
    TenantUpdateRequest,
)

__all__ = [
    "AdminContextOut",
    "AdminUserCreateRequest",
    "AdminUserOut",
    "AdminUserResetPasswordRequest",
    "AdminUserUpdateRequest",
    "AppEnv",
    "AuditLogOut",
    "ChangePasswordRequest",
    "ComponentOut",
    "ComponentPayload",
    "LoginRequest",
    "LoginResponse",
    "PageOut",
    "PasswordPolicyOut",
    "PromptOut",
    "PromptPayload",
    "PublicContextOut",
    "RefreshRequest",
    "ResourcePayload",
    "SkillOut",
    "SkillPayload",
    "TenantCreateRequest",
    "TenantOut",
    "TenantResolution",
    "TenantSwitchMode",
    "TenantUpdateRequest",
    "ToolOut",
    "ToolPayload",
]
