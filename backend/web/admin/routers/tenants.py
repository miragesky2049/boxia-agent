"""租户管理接口（仅产品级运营管理平台）。"""

from fastapi import APIRouter, Depends, Query, Request, status

from web.admin.schemas.common import PageOut
from web.admin.schemas.tenant import TenantCreateRequest, TenantOut, TenantUpdateRequest
from web.deps.auth import PlatformSuperadminDep, require_platform_superadmin
from web.deps.services import TenantServiceDep

router = APIRouter(
    prefix="/tenants",
    tags=["admin-tenants"],
    dependencies=[Depends(require_platform_superadmin)],
)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent


@router.get("", response_model=PageOut[TenantOut])
def list_tenants(
    service: TenantServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
) -> PageOut[TenantOut]:
    """分页查询全部租户。"""
    tenants = service.list_tenants(keyword)
    start = (page - 1) * page_size
    return PageOut[TenantOut](
        items=[TenantOut.model_validate(item) for item in tenants[start : start + page_size]],
        total=len(tenants),
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreateRequest,
    request: Request,
    service: TenantServiceDep,
    principal: PlatformSuperadminDep,
) -> TenantOut:
    """创建租户并初始化租户级超级管理员。"""
    ip, user_agent = _client_meta(request)
    tenant = service.create(
        code=payload.code,
        name=payload.name,
        admin_username=payload.admin_username,
        admin_password=payload.admin_password,
        admin_display_name=payload.admin_display_name,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return TenantOut.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: int, service: TenantServiceDep) -> TenantOut:
    """查询租户详情。"""
    return TenantOut.model_validate(service.get(tenant_id))


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: int,
    payload: TenantUpdateRequest,
    request: Request,
    service: TenantServiceDep,
    principal: PlatformSuperadminDep,
) -> TenantOut:
    """更新租户名称或启用状态。"""
    ip, user_agent = _client_meta(request)
    tenant = service.update(
        tenant_id,
        name=payload.name,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return TenantOut.model_validate(tenant)
