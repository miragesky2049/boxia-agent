"""当前管理端作用域信息接口。"""

from fastapi import APIRouter

from internal.infrastructure.config.settings import get_settings
from web.admin.schemas.auth import AdminUserOut
from web.admin.schemas.context import AdminContextOut
from web.admin.schemas.tenant import PasswordPolicyOut, TenantOut
from web.deps.auth import AdminAuthDep, AdminPrincipal
from web.deps.services import AuthServiceDep
from web.deps.tenant import RequestContextDep, tenant_switch_mode

router = APIRouter(prefix="/context", tags=["admin-context"])


def _menus(principal: AdminPrincipal) -> list[str]:
    """按作用域与系统角色返回可见菜单 key，前端仅用于渲染。

    平台超管维护平台自有角色；平台侧不提供按资源的赠予菜单，租户侧 grants 表示给用户分配角色。
    """
    menus = ["agents"]
    if principal.system_role != "superadmin":
        return menus
    if principal.is_platform:
        return [*menus, "roles", "admin-users", "tenants", "audit"]
    return [*menus, "grants", "roles", "users", "admin-users", "audit"]


@router.get("", response_model=AdminContextOut)
def get_admin_context(
    principal: AdminAuthDep,
    context: RequestContextDep,
    service: AuthServiceDep,
) -> AdminContextOut:
    """返回当前登录账号所在作用域、租户、环境与域名配置。"""
    settings = get_settings()
    profile = service.get_profile(principal.user_id, principal.tenant_id)
    return AdminContextOut(
        scope=context.scope,
        tenant=TenantOut.model_validate(context.tenant) if context.tenant else None,
        user=AdminUserOut.model_validate(profile),
        role=principal.system_role,
        system_role=principal.system_role,
        permissions=sorted(principal.permissions),
        menus=_menus(principal),
        app_env=settings.app_env,
        tenant_resolution=context.resolution,
        tenant_switch_mode=tenant_switch_mode(settings, context),
        root_domain=settings.normalized_root_domain,
        platform_admin_subdomain=settings.platform_admin_subdomain.strip().lower(),
        platform_admin_host=settings.platform_admin_host,
        platform_name=settings.platform_name,
        password_policy=PasswordPolicyOut.from_settings(settings),
    )
