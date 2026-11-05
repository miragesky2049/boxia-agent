"""租户管理接口（仅产品级运营管理平台）。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from internal.application.apps.tenant_settings_service import TenantSettingsService
from web.admin.schemas.auth import (
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserResetPasswordRequest,
    AdminUserUpdateRequest,
)
from web.admin.schemas.common import PageOut
from web.admin.schemas.tenant import (
    TenantBatchDeleteOut,
    TenantBatchDeleteRequest,
    TenantCreateRequest,
    TenantDeleteOut,
    TenantOut,
    TenantUpdateRequest,
)
from web.deps.apps_services import make_tenant_settings_service
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
from web.deps.db import UowDep
from web.deps.services import AdminUserServiceDep, TenantServiceDep

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


@router.delete(
    "/{tenant_id}",
    response_model=TenantDeleteOut,
    dependencies=[Depends(require_permission("button:tenant:delete"))],
)
def delete_tenant(
    tenant_id: UUID,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
    confirm: bool = Query(..., description="二次确认位，必须为 true"),
) -> TenantDeleteOut:
    """物理删除租户及其全部关联数据（仅平台 superadmin，不可逆）。"""
    ip, user_agent = _client_meta(request)
    result = service.delete(
        tenant_id,
        confirm=confirm,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_code=principal.role_code,
        ip=ip,
        user_agent=user_agent,
    )
    return TenantDeleteOut.model_validate(result)


@router.post(
    "/batch",
    response_model=TenantBatchDeleteOut,
    dependencies=[Depends(require_permission("button:tenant:delete"))],
)
def batch_delete_tenants(
    payload: TenantBatchDeleteRequest,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
) -> TenantBatchDeleteOut:
    """批量物理删除租户：逐租户独立事务，部分成功，返回每项明细。"""
    ip, user_agent = _client_meta(request)
    result = service.batch_delete(
        payload.tenant_ids,
        confirm=payload.confirm,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_code=principal.role_code,
        ip=ip,
        user_agent=user_agent,
        reason=payload.reason,
    )
    return TenantBatchDeleteOut.model_validate(result)


# ========== T16 租户运行时配置（默认模型 + 插件白名单）==========
class TenantSettingsUpdateRequest(BaseModel):
    default_model_catalog_id: UUID | None = Field(None, description="默认模型 catalog id；置空表示走平台默认")
    allowed_catalog_ids: list[UUID] = Field(default_factory=list, description="允许该租户可见的模型白名单；空数组=全量可见")
    plugin_whitelist: list[str] = Field(default_factory=list, description="允许调用的工具名白名单；空数组=全量可见")


def _get_settings_service(uow: UowDep) -> TenantSettingsService:
    return make_tenant_settings_service(uow.session)


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


# ========== 租户管理员账号（平台管理员跨租户管理）==========
@router.get(
    "/{tenant_id}/admins",
    response_model=PageOut[AdminUserOut],
    dependencies=[Depends(require_permission("page:admin-users"))],
)
def list_tenant_admins(
    tenant_id: UUID,
    service: AdminUserServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
) -> PageOut[AdminUserOut]:
    """平台管理员分页查询指定租户的管理员账号。"""
    result = service.list_for_tenant(tenant_id, page, page_size, keyword)
    return PageOut[AdminUserOut](
        items=[AdminUserOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/{tenant_id}/admins",
    response_model=AdminUserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:admin-user:create"))],
)
def create_tenant_admin(
    tenant_id: UUID,
    payload: AdminUserCreateRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> AdminUserOut:
    """平台管理员为指定租户新建管理员账号。"""
    ip, user_agent = _client_meta(request)
    user = service.create_for_tenant(
        tenant_id,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role_id=payload.role_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return AdminUserOut.model_validate(user)


@router.patch(
    "/{tenant_id}/admins/{user_id}",
    response_model=AdminUserOut,
    dependencies=[Depends(require_permission("button:admin-user:update"))],
)
def update_tenant_admin(
    tenant_id: UUID,
    user_id: UUID,
    payload: AdminUserUpdateRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> AdminUserOut:
    """平台管理员调整指定租户的管理员账号。"""
    ip, user_agent = _client_meta(request)
    user = service.update_for_tenant(
        tenant_id,
        user_id,
        display_name=payload.display_name,
        role_id=payload.role_id,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return AdminUserOut.model_validate(user)


@router.delete(
    "/{tenant_id}/admins/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:admin-user:delete"))],
)
def delete_tenant_admin(
    tenant_id: UUID,
    user_id: UUID,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> None:
    """平台管理员删除指定租户的管理员账号。"""
    ip, user_agent = _client_meta(request)
    service.delete_for_tenant(
        tenant_id,
        user_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.post(
    "/{tenant_id}/admins/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:admin-user:reset-password"))],
)
def reset_tenant_admin_password(
    tenant_id: UUID,
    user_id: UUID,
    payload: AdminUserResetPasswordRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> None:
    """平台管理员重置指定租户管理员密码。"""
    ip, user_agent = _client_meta(request)
    service.reset_password_for_tenant(
        tenant_id,
        user_id,
        new_password=payload.new_password,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
