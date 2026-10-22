"""匿名可访问的作用域信息接口（登录页、本地调试租户切换）。"""

from fastapi import APIRouter

from internal.application.errors import ForbiddenError
from internal.infrastructure.config.settings import get_settings
from web.admin.schemas import PublicContextOut, TenantOut
from web.deps.services import TenantServiceDep
from web.deps.tenant import RequestContextDep, tenant_switch_mode

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/context", response_model=PublicContextOut)
def get_public_context(context: RequestContextDep) -> PublicContextOut:
    """按当前域名返回产品级/租户级模式、环境与解析来源，供登录页展示。"""
    settings = get_settings()
    return PublicContextOut(
        scope=context.scope,
        tenant=TenantOut.model_validate(context.tenant) if context.tenant else None,
        app_env=settings.app_env,
        tenant_resolution=context.resolution,
        tenant_switch_mode=tenant_switch_mode(settings, context),
        root_domain=settings.normalized_root_domain,
        platform_admin_subdomain=settings.platform_admin_subdomain.strip().lower(),
        platform_admin_host=settings.platform_admin_host,
        platform_name=settings.platform_name,
    )


@router.get("/tenants", response_model=list[TenantOut])
def list_selectable_tenants(
    context: RequestContextDep, service: TenantServiceDep
) -> list[TenantOut]:
    """仅本地调试返回可选租户；开发/测试/线上不暴露租户列表。"""
    settings = get_settings()
    if not settings.is_local:
        raise ForbiddenError("当前环境未开启租户切换")
    tenants = service.list_active()
    return [TenantOut.model_validate(item) for item in tenants]
