"""当前站点作用域上下文模型。"""

from pydantic import BaseModel

from web.admin.schemas.auth import AdminUserOut
from web.admin.schemas.tenant import (
    AppEnv,
    PasswordPolicyOut,
    TenantOut,
    TenantResolution,
    TenantSwitchMode,
)


class AdminContextOut(BaseModel):
    """当前管理端作用域上下文。"""

    scope: str
    tenant: TenantOut | None
    user: AdminUserOut
    app_env: AppEnv
    tenant_resolution: TenantResolution
    tenant_switch_mode: TenantSwitchMode
    root_domain: str
    platform_admin_subdomain: str
    platform_admin_host: str
    platform_name: str
    password_policy: PasswordPolicyOut


class PublicContextOut(BaseModel):
    """登录页等匿名场景使用的作用域上下文。"""

    scope: str
    tenant: TenantOut | None
    app_env: AppEnv
    tenant_resolution: TenantResolution
    tenant_switch_mode: TenantSwitchMode
    root_domain: str
    platform_admin_subdomain: str
    platform_admin_host: str
    platform_name: str
    password_policy: PasswordPolicyOut
