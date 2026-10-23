"""当前管理端作用域信息接口。"""

from fastapi import APIRouter

from internal.infrastructure.config.settings import get_settings
from web.admin.schemas.auth import AdminUserOut
from web.admin.schemas.context import AdminContextOut
from web.admin.schemas.tenant import PasswordPolicyOut, TenantOut
from web.deps.auth import AdminAuthDep
from web.deps.services import AuthServiceDep
from web.deps.tenant import RequestContextDep, tenant_switch_mode

router = APIRouter(prefix="/context", tags=["admin-context"])


@router.get("", response_model=AdminContextOut)
def get_admin_context(
    principal: AdminAuthDep,
    context: RequestContextDep,
    service: AuthServiceDep,
) -> AdminContextOut:
    """返回当前登录账号所在作用域、租户、环境与域名配置。"""
    settings = get_settings()
    profile = service.get_profile(principal.user_id)
    return AdminContextOut(
        scope=context.scope,
        tenant=TenantOut.model_validate(context.tenant) if context.tenant else None,
        user=AdminUserOut.model_validate(profile),
        app_env=settings.app_env,
        tenant_resolution=context.resolution,
        tenant_switch_mode=tenant_switch_mode(settings, context),
        root_domain=settings.normalized_root_domain,
        platform_admin_subdomain=settings.platform_admin_subdomain.strip().lower(),
        platform_admin_host=settings.platform_admin_host,
        platform_name=settings.platform_name,
        password_policy=PasswordPolicyOut.from_settings(settings),
    )
