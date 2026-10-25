"""角色管理接口：角色 CRUD、功能权限与资源授权维护。"""

from fastapi import APIRouter, Depends, Query, Request, status

from web.admin.schemas.common import PageOut
from web.admin.schemas.role import (
    RoleCopyRequest,
    RoleCreateRequest,
    RoleOut,
    RoleUpdateRequest,
)
from web.admin.schemas.role_grant import (
    RoleGrantAddRequest,
    RoleGrantReplaceRequest,
    RoleGrantResourceOut,
    RoleGrantSummaryOut,
    RoleGrantUpdateOut,
)
from web.admin.schemas.role_permission import (
    PermissionResourceOut,
    RolePermissionAddRequest,
    RolePermissionListOut,
    RolePermissionReplaceRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import (
    RoleGrantServiceDep,
    RolePermissionServiceDep,
    RoleServiceDep,
)

router = APIRouter(prefix="/roles", tags=["admin-roles"])

_VIEW_ROLES = Depends(require_permission("page:roles"))
_GRANT_ROLES = Depends(require_permission("button:role:grant"))


@router.get("", response_model=list[RoleOut], dependencies=[_VIEW_ROLES])
def list_roles(
    service: RoleServiceDep,
    tenant_id: int | None = Query(None, ge=1),
    include_inactive: bool = Query(False),
) -> list[RoleOut]:
    """查询角色；平台只返回平台角色，租户只返回本租户角色。"""
    return [RoleOut.model_validate(item) for item in service.list(tenant_id, include_inactive)]


@router.get("/{role_id}", response_model=RoleOut, dependencies=[_VIEW_ROLES])
def get_role(
    role_id: int,
    service: RoleServiceDep,
    tenant_id: int | None = Query(None, ge=1),
) -> RoleOut:
    """查询角色详情；平台只返回平台角色，租户只返回本租户角色。"""
    return RoleOut.model_validate(service.get(role_id, tenant_id))


@router.post(
    "",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:role:create"))],
)
def create_role(
    payload: RoleCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RoleServiceDep,
) -> RoleOut:
    """创建当前作用域的角色；产品级入口创建的角色为系统角色。"""
    ip, user_agent = client_meta(request)
    role = service.create(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RoleOut.model_validate(role)


@router.post(
    "/{role_id}/copy",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:role:copy"))],
)
def copy_role(
    role_id: int,
    payload: RoleCopyRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RoleServiceDep,
) -> RoleOut:
    """复制角色及其功能权限与资源授权，生成新的自定义角色。"""
    ip, user_agent = client_meta(request)
    role = service.copy(
        role_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        actor_permissions=principal.permissions,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RoleOut.model_validate(role)


@router.patch(
    "/{role_id}",
    response_model=RoleOut,
    dependencies=[Depends(require_permission("button:role:update"))],
)
def update_role(
    role_id: int,
    payload: RoleUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RoleServiceDep,
) -> RoleOut:
    """更新角色名称、描述与启用状态；功能权限通过授权接口维护。"""
    ip, user_agent = client_meta(request)
    role = service.update(
        role_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RoleOut.model_validate(role)


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:role:delete"))],
)
def delete_role(
    role_id: int,
    principal: AdminAuthDep,
    request: Request,
    service: RoleServiceDep,
) -> None:
    """删除角色；被账号或授权引用时拒绝。"""
    ip, user_agent = client_meta(request)
    service.delete(
        role_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.get(
    "/{role_id}/permissions",
    response_model=RolePermissionListOut,
    dependencies=[_VIEW_ROLES],
)
def list_role_permissions(
    role_id: int,
    service: RolePermissionServiceDep,
) -> RolePermissionListOut:
    """查询角色已授予的功能权限。"""
    items = service.list_for_role(role_id)
    return RolePermissionListOut(
        items=[PermissionResourceOut.model_validate(item) for item in items],
        codes=[item.code for item in items],
    )


@router.put(
    "/{role_id}/permissions",
    response_model=RolePermissionListOut,
    dependencies=[_GRANT_ROLES],
)
def replace_role_permissions(
    role_id: int,
    payload: RolePermissionReplaceRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RolePermissionServiceDep,
) -> RolePermissionListOut:
    """整体替换角色功能权限；不能授予自身不具备的权限。"""
    ip, user_agent = client_meta(request)
    items = service.replace(
        role_id,
        payload.codes,
        actor_permissions=principal.permissions,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RolePermissionListOut(
        items=[PermissionResourceOut.model_validate(item) for item in items],
        codes=[item.code for item in items],
    )


@router.post(
    "/{role_id}/permissions",
    response_model=RolePermissionListOut,
    dependencies=[_GRANT_ROLES],
)
def add_role_permissions(
    role_id: int,
    payload: RolePermissionAddRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RolePermissionServiceDep,
) -> RolePermissionListOut:
    """为角色追加功能权限；不能授予自身不具备的权限。"""
    ip, user_agent = client_meta(request)
    items = service.add(
        role_id,
        payload.codes,
        actor_permissions=principal.permissions,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RolePermissionListOut(
        items=[PermissionResourceOut.model_validate(item) for item in items],
        codes=[item.code for item in items],
    )


@router.delete(
    "/{role_id}/permissions/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_GRANT_ROLES],
)
def remove_role_permission(
    role_id: int,
    code: str,
    principal: AdminAuthDep,
    request: Request,
    service: RolePermissionServiceDep,
) -> None:
    """移除角色对单个功能权限的授权。"""
    ip, user_agent = client_meta(request)
    service.remove(
        role_id,
        code,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.get(
    "/{role_id}/grants/summary",
    response_model=RoleGrantSummaryOut,
    dependencies=[_VIEW_ROLES],
)
def get_role_grant_summary(
    role_id: int,
    service: RoleGrantServiceDep,
) -> RoleGrantSummaryOut:
    """按资源类型返回角色有效授权数量。"""
    return RoleGrantSummaryOut(counts=service.summary(role_id))


@router.get(
    "/{role_id}/grants",
    response_model=PageOut[RoleGrantResourceOut],
    dependencies=[_VIEW_ROLES],
)
def list_role_grants(
    role_id: int,
    service: RoleGrantServiceDep,
    resource_type: str = Query(..., max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    granted_only: bool = Query(True),
) -> PageOut[RoleGrantResourceOut]:
    """按资源分类查询角色授权；可切换为全部候选资源。"""
    result = service.list(role_id, resource_type, page, page_size, keyword, granted_only)
    return PageOut[RoleGrantResourceOut](
        items=[RoleGrantResourceOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.put(
    "/{role_id}/grants/{resource_type}",
    response_model=RoleGrantUpdateOut,
    dependencies=[_GRANT_ROLES],
)
def replace_role_grants(
    role_id: int,
    resource_type: str,
    payload: RoleGrantReplaceRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RoleGrantServiceDep,
) -> RoleGrantUpdateOut:
    """整体替换角色在某类资源上的授权。"""
    ip, user_agent = client_meta(request)
    updated = service.replace(
        role_id,
        resource_type,
        payload.resource_ids,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RoleGrantUpdateOut(updated=updated)


@router.post(
    "/{role_id}/grants/{resource_type}",
    response_model=RoleGrantUpdateOut,
    dependencies=[_GRANT_ROLES],
)
def add_role_grants(
    role_id: int,
    resource_type: str,
    payload: RoleGrantAddRequest,
    principal: AdminAuthDep,
    request: Request,
    service: RoleGrantServiceDep,
) -> RoleGrantUpdateOut:
    """为角色追加资源授权。"""
    ip, user_agent = client_meta(request)
    added = service.add(
        role_id,
        resource_type,
        payload.resource_ids,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return RoleGrantUpdateOut(updated=added)


@router.delete(
    "/{role_id}/grants/{resource_type}/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_GRANT_ROLES],
)
def remove_role_grant(
    role_id: int,
    resource_type: str,
    resource_id: int,
    principal: AdminAuthDep,
    request: Request,
    service: RoleGrantServiceDep,
) -> None:
    """移除角色对单个资源的授权。"""
    ip, user_agent = client_meta(request)
    service.remove(
        role_id,
        resource_type,
        resource_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
