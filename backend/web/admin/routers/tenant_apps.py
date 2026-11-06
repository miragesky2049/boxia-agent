"""租户侧应用可见范围/管理范围接口（挂在 /admin/tenant/apps 下，仅租户管理端可访问）。"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from internal.application.apps.admin_scope_service import AdminScopeService
from internal.application.apps.application_service import ApplicationService
from internal.application.errors import ForbiddenError
from web.deps.apps_services import make_admin_scope_service, make_application_service
from web.deps.auth import AdminPrincipal, TenantAdminDep
from web.deps.db import UowDep

router = APIRouter(prefix="/tenant/apps", tags=["tenant-apps"])


def _tenant_of(principal: AdminPrincipal) -> UUID:
    """租户管理端 principal 恒有 tenant_id（require_tenant_admin 已拒绝平台作用域），此处仅做类型收窄。"""
    if principal.tenant_id is None:
        raise ForbiddenError("无法识别租户")
    return principal.tenant_id


def get_app_service(uow: UowDep) -> ApplicationService:
    return make_application_service(uow)


def get_admin_scope_service(uow: UowDep) -> AdminScopeService:
    return make_admin_scope_service(uow)


AppServiceDep = Depends(get_app_service)
AdminScopeServiceDep = Depends(get_admin_scope_service)


class WhitelistItem(BaseModel):
    subject_type: Literal["DEPARTMENT", "ROLE", "USER"]
    subject_id: str = Field(..., min_length=1, max_length=64)
    include_subtree: bool = False


class VisibilityPayload(BaseModel):
    visibility: Literal["all", "whitelist"]
    whitelist: list[WhitelistItem] = Field(default_factory=list)


@router.get("/{application_id}/visibility")
def get_visibility(
    application_id: UUID,
    principal: TenantAdminDep,
    service: ApplicationService = AppServiceDep,
    scope_service: AdminScopeService = AdminScopeServiceDep,
) -> dict:
    """读取本租户内某应用的可见范围（未配置时按平台模板兜底，带 configured 标记）。

    附 manageable 标记：当前用户是否可管理该应用，前端据此渲染只读详情。
    """
    tenant_id = _tenant_of(principal)
    result = service.get_tenant_visibility(application_id, tenant_id)
    result["manageable"] = scope_service.is_manageable(application_id, tenant_id, principal.user_id)
    return result


@router.put("/{application_id}/visibility")
def replace_visibility(
    application_id: UUID,
    payload: VisibilityPayload,
    principal: TenantAdminDep,
    service: ApplicationService = AppServiceDep,
    scope_service: AdminScopeService = AdminScopeServiceDep,
) -> dict:
    """覆盖写入本租户可见范围。

    门槛：app:visibility:write + 管理范围鉴权（assert_manageable）；
    平台锁定（visibility_lock）时 403。
    """
    if not principal.can("app:visibility:write"):
        raise ForbiddenError("缺少可见范围编辑权限")
    tenant_id = _tenant_of(principal)
    scope_service.assert_manageable(application_id, tenant_id, principal.user_id)
    whitelist = [item.model_dump() for item in payload.whitelist]
    return service.replace_tenant_visibility(
        application_id,
        tenant_id,
        payload.visibility,
        whitelist,
    )


@router.get("")
def list_subscribed_apps(
    principal: TenantAdminDep,
    scope_service: AdminScopeService = AdminScopeServiceDep,
    scope: Annotated[Literal["all", "managed"], Query(description="all=全部订阅；managed=我管理的")] = "all",
) -> list[dict]:
    """列出当前租户已订阅的产品级应用（管理列表数据源）。

    返回每个应用的基础信息 + visibility_lock 状态 + manageable 标记
    （当前用户按管理范围能否管理该应用），
    前端据此决定「应用配置」进入后是否只读。
    scope=managed 时仅返回当前用户可管理的应用（0069 二期）。
    """
    apps = scope_service.list_subscribed_apps(principal.user_id, _tenant_of(principal))
    if scope == "managed":
        return [app for app in apps if app["manageable"]]
    return apps


class AdminScopePayload(BaseModel):
    mgmt_unit_id: UUID


@router.get("/{application_id}/admin-scope")
def list_admin_scopes(
    application_id: UUID,
    principal: TenantAdminDep,
    service: AdminScopeService = AdminScopeServiceDep,
) -> list[dict]:
    """列出应用关联的管理单元（查看不设管理范围门槛，编辑另校验）。"""
    return service.list_scopes(application_id, _tenant_of(principal))


@router.post("/{application_id}/admin-scope")
def add_admin_scope(
    application_id: UUID,
    payload: AdminScopePayload,
    principal: TenantAdminDep,
    service: AdminScopeService = AdminScopeServiceDep,
) -> dict:
    """新增应用与管理单元关联：需 app:admin_scope:write 且通过管理范围鉴权。"""
    if not principal.can("app:admin_scope:write"):
        raise ForbiddenError("缺少管理范围编辑权限")
    service.add_scope(application_id, _tenant_of(principal), principal.user_id, payload.mgmt_unit_id)
    return {"application_id": str(application_id), "mgmt_unit_id": str(payload.mgmt_unit_id)}


@router.delete("/{application_id}/admin-scope/{mgmt_unit_id}")
def remove_admin_scope(
    application_id: UUID,
    mgmt_unit_id: UUID,
    principal: TenantAdminDep,
    service: AdminScopeService = AdminScopeServiceDep,
) -> dict:
    """解除应用与管理单元关联：需 app:admin_scope:write 且通过管理范围鉴权。"""
    if not principal.can("app:admin_scope:write"):
        raise ForbiddenError("缺少管理范围编辑权限")
    service.remove_scope(
        application_id, _tenant_of(principal), principal.user_id, mgmt_unit_id
    )
    return {"application_id": str(application_id), "mgmt_unit_id": str(mgmt_unit_id)}
