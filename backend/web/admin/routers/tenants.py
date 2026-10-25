"""租户管理接口（仅产品级运营管理平台）。"""

from fastapi import APIRouter, Depends, Query, Request, status

from internal.application.tenant_service import TenantAgentView
from web.admin.schemas.common import PageOut
from web.admin.schemas.tenant import (
    TenantAgentBatchOpenOut,
    TenantAgentBatchOpenRequest,
    TenantAgentOpenOut,
    TenantAgentOpenRequest,
    TenantAgentOut,
    TenantCreateRequest,
    TenantOut,
    TenantUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
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
def get_tenant(tenant_id: int, service: TenantServiceDep) -> TenantOut:
    """查询租户详情。"""
    return TenantOut.model_validate(service.get(tenant_id))


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    dependencies=[Depends(require_permission("button:tenant:update"))],
)
def update_tenant(
    tenant_id: int,
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


@router.get(
    "/{tenant_id}/agents",
    response_model=PageOut[TenantAgentOut],
    dependencies=[Depends(require_permission("page:tenants"))],
)
def list_tenant_agents(
    tenant_id: int,
    service: TenantServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
    opened_only: bool = Query(False),
) -> PageOut[TenantAgentOut]:
    """分页查询产品智能体及该租户的开通状态。"""
    result = service.list_agents(
        tenant_id, page, page_size, keyword, is_enabled, opened_only
    )
    return PageOut[TenantAgentOut](
        items=[_to_tenant_agent_out(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/{tenant_id}/agents/batch",
    response_model=TenantAgentBatchOpenOut,
    dependencies=[Depends(require_permission("button:tenant:update"))],
)
def set_tenant_agents_opened(
    tenant_id: int,
    payload: TenantAgentBatchOpenRequest,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
) -> TenantAgentBatchOpenOut:
    """批量开通或关闭租户对产品智能体的访问。"""
    ip, user_agent = _client_meta(request)
    agent_ids = service.set_agents_opened(
        tenant_id,
        payload.agent_ids,
        payload.opened,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return TenantAgentBatchOpenOut(
        tenant_id=tenant_id,
        opened=payload.opened,
        count=len(agent_ids),
        agent_ids=agent_ids,
    )


@router.put(
    "/{tenant_id}/agents/{agent_id}",
    response_model=TenantAgentOpenOut,
    dependencies=[Depends(require_permission("button:tenant:update"))],
)
def set_tenant_agent_opened(
    tenant_id: int,
    agent_id: int,
    payload: TenantAgentOpenRequest,
    request: Request,
    service: TenantServiceDep,
    principal: AdminAuthDep,
) -> TenantAgentOpenOut:
    """开通或关闭租户对产品智能体的访问。"""
    ip, user_agent = _client_meta(request)
    opening = service.set_agent_opened(
        tenant_id,
        agent_id,
        payload.opened,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return TenantAgentOpenOut(
        agent_id=agent_id,
        tenant_id=tenant_id,
        is_opened=opening is not None,
        opened_at=opening.opened_at if opening else None,
    )


def _to_tenant_agent_out(item: TenantAgentView) -> TenantAgentOut:
    return TenantAgentOut(
        id=item.agent.id,
        name=item.agent.name,
        avatar_url=item.agent.avatar_url,
        description=item.agent.description,
        is_enabled=item.agent.is_enabled,
        is_opened=item.is_opened,
        opened_at=item.opening.opened_at if item.opening else None,
        opened_by=item.opening.opened_by if item.opening else None,
    )
