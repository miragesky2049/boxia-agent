"""用户端智能体查询接口：仅返回当前角色可见且启用的内容。"""

from fastapi import APIRouter, Query

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Agent
from web.deps.services import UserPortalServiceDep
from web.user.schemas.agent import (
    UserAgentDetailOut,
    UserAgentSummaryOut,
    UserComponentOut,
    UserPromptOut,
    UserSkillOut,
    UserToolOut,
)
from web.user.schemas.common import PageOut

router = APIRouter(prefix="/agents", tags=["user-agents"])


@router.get("", response_model=PageOut[UserAgentSummaryOut])
def list_agents(
    service: UserPortalServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
) -> PageOut[UserAgentSummaryOut]:
    """分页查询当前用户可见的智能体。"""
    return _to_page_out(service.list_agents(page, page_size, keyword))


@router.get("/{agent_id}", response_model=UserAgentDetailOut)
def get_agent(agent_id: int, service: UserPortalServiceDep) -> UserAgentDetailOut:
    """查询智能体详情及已授权的技能/工具/组件/提示词。"""
    bundle = service.get_agent(agent_id)
    return UserAgentDetailOut(
        id=bundle.agent.id,
        name=bundle.agent.name,
        avatar_url=bundle.agent.avatar_url,
        description=bundle.agent.description,
        is_enabled=bundle.agent.is_enabled,
        config=bundle.agent.config,
        skills=[UserSkillOut.model_validate(item) for item in bundle.skills],
        tools=[UserToolOut.model_validate(item) for item in bundle.tools],
        components=[UserComponentOut.model_validate(item) for item in bundle.components],
        prompts=[UserPromptOut.model_validate(item) for item in bundle.prompts],
    )


def _to_page_out(result: Page[Agent]) -> PageOut[UserAgentSummaryOut]:
    return PageOut[UserAgentSummaryOut](
        items=[UserAgentSummaryOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
