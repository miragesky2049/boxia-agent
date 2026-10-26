"""智能体管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from internal.application.tenant_service import AgentTenantView
from internal.domain.entity.common import Page
from internal.domain.entity.resource import Agent
from web.admin.schemas.agent import AgentOut, AgentPayload, AgentSummaryOut
from web.admin.schemas.common import PageOut
from web.admin.schemas.tenant import AgentOpenedTenantOut
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
from web.deps.services import AgentServiceDep, TenantServiceDep

router = APIRouter(prefix="/agents", tags=["admin-agents"])


@router.get(
    "",
    response_model=PageOut[AgentSummaryOut],
    dependencies=[Depends(require_permission("agent:read"))],
)
def list_agents(
    service: AgentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
) -> PageOut[AgentSummaryOut]:
    """分页查询智能体。"""
    result = service.list(page, page_size, keyword, is_enabled)
    return _to_page_out(result)


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("agent:create"))],
)
def create_agent(
    payload: AgentPayload,
    principal: AdminAuthDep,
    service: AgentServiceDep,
) -> AgentOut:
    """创建智能体，并授权给创建者角色；同时记录创建者供"本人数据"范围使用。"""
    agent = service.create(
        payload.model_dump(),
        principal.role_ids,
        actor_user_id=principal.user_id,
    )
    return AgentOut.model_validate(agent)


@router.get(
    "/{agent_id}",
    response_model=AgentOut,
    dependencies=[Depends(require_permission("agent:read"))],
)
def get_agent(agent_id: UUID, service: AgentServiceDep) -> AgentOut:
    """查询智能体详情。"""
    return AgentOut.model_validate(service.get(agent_id))


@router.put(
    "/{agent_id}",
    response_model=AgentOut,
    dependencies=[Depends(require_permission("agent:update"))],
)
def update_agent(agent_id: UUID, payload: AgentPayload, service: AgentServiceDep) -> AgentOut:
    """更新智能体（含配置与工具/技能关联）。"""
    return AgentOut.model_validate(service.update(agent_id, payload.model_dump()))


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("agent:delete"))],
)
def delete_agent(agent_id: UUID, service: AgentServiceDep) -> None:
    """删除智能体。"""
    service.delete(agent_id)


@router.get(
    "/{agent_id}/tenants",
    response_model=PageOut[AgentOpenedTenantOut],
    dependencies=[
        Depends(require_platform_admin),
        Depends(require_permission("page:agents")),
    ],
)
def list_agent_tenants(
    agent_id: UUID,
    service: TenantServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
) -> PageOut[AgentOpenedTenantOut]:
    """分页查询已开通该产品智能体的租户。"""
    result = service.list_agent_tenants(agent_id, page, page_size, keyword)
    return PageOut[AgentOpenedTenantOut](
        items=[_to_agent_tenant_out(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


def _to_agent_tenant_out(item: AgentTenantView) -> AgentOpenedTenantOut:
    return AgentOpenedTenantOut(
        id=item.tenant.id,
        code=item.tenant.code,
        name=item.tenant.name,
        is_active=item.tenant.is_active,
        opened_at=item.opening.opened_at,
        opened_by=item.opening.opened_by,
    )


def _to_page_out(result: Page[Agent]) -> PageOut[AgentSummaryOut]:
    return PageOut[AgentSummaryOut](
        items=[AgentSummaryOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
