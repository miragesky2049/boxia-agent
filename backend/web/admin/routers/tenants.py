"""租户管理接口（仅产品级运营管理平台）。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from internal.application.apps.tenant_settings_service import TenantSettingsService
from web.admin.schemas.common import PageOut
from web.admin.schemas.tenant import (
    TenantCreateRequest,
    TenantOut,
    TenantUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
from web.deps.db import UowDep
from web.deps.services import TenantServiceDep

router = APIRouter(
    prefix="/tenants",
    tags=["admin-tenants"],
    dependencies=[Depends(require_platform_admin)],
)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent


@router.get(
    "",
    response_model=PageOut[TenantOut],
    dependencies=[Depends(require_permission("page:tenants"))],
)
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


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:tenant:create"))],
)
def create_tenant(
    payload: TenantCreateRequest,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
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


@router.get(
    "/{tenant_id}",
    response_model=TenantOut,
    dependencies=[Depends(require_permission("page:tenants"))],
)
def get_tenant(tenant_id: UUID, service: TenantServiceDep) -> TenantOut:
    """查询租户详情。"""
    return TenantOut.model_validate(service.get(tenant_id))


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    dependencies=[Depends(require_permission("button:tenant:update"))],
)
def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdateRequest,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
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


# ========== T16 租户运行时配置（默认模型 + 插件白名单）==========
class TenantSettingsUpdateRequest(BaseModel):
    default_model_catalog_id: UUID | None = Field(None, description="默认模型 catalog id；置空表示走平台默认")
    allowed_catalog_ids: list[UUID] = Field(default_factory=list, description="允许该租户可见的模型白名单；空数组=全量可见")
    plugin_whitelist: list[str] = Field(default_factory=list, description="允许调用的工具名白名单；空数组=全量可见")


def _get_settings_service(uow: UowDep) -> TenantSettingsService:
    return TenantSettingsService(uow.session)


@router.get(
    "/{tenant_id}/settings",
    dependencies=[Depends(require_permission("page:tenants"))],
)
def get_tenant_settings(tenant_id: UUID, uow: UowDep) -> dict[str, Any]:
    """读取租户运行时配置。"""
    return _get_settings_service(uow).get(tenant_id)


@router.put(
    "/{tenant_id}/settings",
    dependencies=[Depends(require_permission("button:tenant:update"))],
)
def update_tenant_settings(
    tenant_id: UUID,
    payload: TenantSettingsUpdateRequest,
    uow: UowDep,
) -> dict[str, Any]:
    """upsert 租户运行时配置（覆盖式写入）。"""
    return _get_settings_service(uow).update(
        tenant_id,
        default_model_catalog_id=payload.default_model_catalog_id,
        allowed_catalog_ids=payload.allowed_catalog_ids,
        plugin_whitelist=payload.plugin_whitelist,
    )
