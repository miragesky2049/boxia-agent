"""智能体管理接口。"""

from fastapi import APIRouter, Depends, Query, status

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Agent
from web.admin.schemas.agent import AgentOut, AgentPayload, AgentSummaryOut
from web.admin.schemas.common import PageOut
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.services import AgentServiceDep

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
    authorized: bool = Query(False),
) -> PageOut[AgentSummaryOut]:
    """分页查询智能体；authorized 仅保留已有租户授权的平台智能体。"""
    result = service.list(page, page_size, keyword, is_enabled, authorized)
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
    """创建智能体，并授权给创建者角色。"""
    return AgentOut.model_validate(service.create(payload.model_dump(), principal.role_ids))


@router.get(
    "/{agent_id}",
    response_model=AgentOut,
    dependencies=[Depends(require_permission("agent:read"))],
)
def get_agent(agent_id: int, service: AgentServiceDep) -> AgentOut:
    """查询智能体详情。"""
    return AgentOut.model_validate(service.get(agent_id))


@router.put(
    "/{agent_id}",
    response_model=AgentOut,
    dependencies=[Depends(require_permission("agent:update"))],
)
def update_agent(agent_id: int, payload: AgentPayload, service: AgentServiceDep) -> AgentOut:
    """更新智能体（含配置与工具/技能关联）。"""
    return AgentOut.model_validate(service.update(agent_id, payload.model_dump()))


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("agent:delete"))],
)
def delete_agent(agent_id: int, service: AgentServiceDep) -> None:
    """删除智能体。"""
    service.delete(agent_id)


def _to_page_out(result: Page[Agent]) -> PageOut[AgentSummaryOut]:
    return PageOut[AgentSummaryOut](
        items=[AgentSummaryOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
