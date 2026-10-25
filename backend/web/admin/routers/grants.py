"""资源授权管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from web.admin.schemas.common import PageOut
from web.admin.schemas.grant import (
    GrantBatchOut,
    GrantBatchRequest,
    GrantOut,
    GrantOverviewOut,
    GrantReplaceRequest,
    UserRoleGrantRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import GrantServiceDep

router = APIRouter(prefix="/grants", tags=["admin-grants"])

_VIEW_GRANTS = Depends(require_permission("page:grants"))
_MANAGE_GRANTS = Depends(require_permission("button:grant:manage"))


@router.get(
    "/overview",
    response_model=PageOut[GrantOverviewOut],
    dependencies=[_VIEW_GRANTS],
)
def overview_grants(
    service: GrantServiceDep,
    resource_type: str = Query(..., max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    grant_state: str | None = Query(None, max_length=16),
) -> PageOut[GrantOverviewOut]:
    """分页查询当前作用域可授权资源及授权汇总。"""
    result = service.overview(resource_type, page, page_size, keyword, grant_state)
    return PageOut[GrantOverviewOut](
        items=[GrantOverviewOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.put(
    "/batch",
    response_model=GrantBatchOut,
    dependencies=[_MANAGE_GRANTS],
)
def replace_grants_batch(
    payload: GrantBatchRequest,
    principal: AdminAuthDep,
    request: Request,
    service: GrantServiceDep,
) -> GrantBatchOut:
    """批量授权；所有模式都只作用于请求指定的租户。"""
    ip, user_agent = client_meta(request)
    updated = service.replace_batch(
        payload.resource_type,
        payload.resource_ids,
        payload.mode,
        payload.tenant_id,
        payload.role_ids,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return GrantBatchOut(updated=updated)


@router.post(
    "/users",
    response_model=GrantBatchOut,
    dependencies=[_MANAGE_GRANTS],
)
def assign_user_roles(
    payload: UserRoleGrantRequest,
    principal: AdminAuthDep,
    request: Request,
    service: GrantServiceDep,
) -> GrantBatchOut:
    """批量给用户追加角色。"""
    ip, user_agent = client_meta(request)
    added = service.assign_user_roles(
        payload.user_ids,
        payload.role_ids,
        payload.tenant_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return GrantBatchOut(updated=added)


@router.get(
    "",
    response_model=list[GrantOut],
    dependencies=[_VIEW_GRANTS],
)
def list_grants(
    service: GrantServiceDep,
    resource_type: str = Query(..., max_length=16),
    resource_id: UUID = Query(...),
    tenant_id: UUID | None = Query(None),
) -> list[GrantOut]:
    """查询资源授权；平台可限定租户，租户视角只返回本租户授权。"""
    return [
        GrantOut.model_validate(item)
        for item in service.list_grants(resource_type, resource_id, tenant_id)
    ]


@router.put(
    "",
    response_model=list[GrantOut],
    dependencies=[_MANAGE_GRANTS],
)
def replace_grants(
    payload: GrantReplaceRequest,
    principal: AdminAuthDep,
    request: Request,
    service: GrantServiceDep,
    resource_type: str = Query(..., max_length=16),
    resource_id: UUID = Query(...),
) -> list[GrantOut]:
    """整体替换资源授权，写审计并返回最新授权列表。"""
    ip, user_agent = client_meta(request)
    grants = service.replace(
        resource_type,
        resource_id,
        [(item.tenant_id, item.role_id) for item in payload.grants],
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return [GrantOut.model_validate(item) for item in grants]
