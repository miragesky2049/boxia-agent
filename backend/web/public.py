"""匿名可访问的作用域信息接口（登录页、开发态租户切换）。"""

from fastapi import APIRouter

from internal.application.errors import ForbiddenError
from internal.infrastructure.config.settings import get_settings
from web.admin.schemas import PublicContextOut, TenantOut
from web.deps.services import TenantServiceDep
from web.deps.tenant import RequestContextDep

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/context", response_model=PublicContextOut)
def get_public_context(context: RequestContextDep) -> PublicContextOut:
    """按当前域名返回产品级/租户级模式，供登录页展示。"""
    settings = get_settings()
    return PublicContextOut(
        scope=context.scope,
        tenant=TenantOut.model_validate(context.tenant) if context.tenant else None,
        root_domain=settings.normalized_root_domain,
        platform_admin_subdomain=settings.platform_admin_subdomain.strip().lower(),
        platform_name=settings.platform_name,
        dev_tenant_switch=settings.tenant_header_enabled,
    )


@router.get("/tenants", response_model=list[TenantOut])
def list_selectable_tenants(
    context: RequestContextDep, service: TenantServiceDep
) -> list[TenantOut]:
    """开发/测试环境返回可选租户，生产环境不可用。"""
    settings = get_settings()
    if not settings.tenant_header_enabled:
        raise ForbiddenError("当前环境未开启租户切换")
    tenants = service.list_active()
    return [TenantOut.model_validate(item) for item in tenants]
