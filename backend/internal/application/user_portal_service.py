"""用户端智能体查询用例：仅返回当前最终用户角色可访问且启用的内容。"""

from dataclasses import dataclass
from typing import Any

from internal.application.errors import ForbiddenError, NotFoundError
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.resource import Agent
from internal.domain.repository.protocols import UnitOfWork


@dataclass(frozen=True)
class AgentBundle:
    """用户端智能体详情：智能体本体 + 已授权且启用的资源。"""

    agent: Agent
    skills: list[Any]
    tools: list[Any]
    components: list[Any]
    prompts: list[Any]


class UserPortalService:
    """用户端只读查询；可见性由作用域仓储统一保证。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list_agents(
        self, page: int, page_size: int, keyword: str | None = None
    ) -> Page[Agent]:
        """分页查询当前用户可见且启用的智能体。"""
        if self._context.is_platform:
            raise ForbiddenError("用户端仅支持通过租户子域名访问")
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.agents.list_page(page, page_size, keyword, True)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get_agent(self, agent_id: int) -> AgentBundle:
        """查询智能体详情及可见资源；无权限与不存在统一返回 404。"""
        agent = self._uow.agents.get(agent_id)
        if agent is None or not agent.is_enabled:
            raise NotFoundError("智能体不存在或未授权")
        return AgentBundle(
            agent=agent,
            skills=self._uow.skills.list_for_agent(agent_id, True),
            tools=self._uow.tools.list_for_agent(agent_id, True),
            components=self._uow.components.list_for_agent(agent_id, True),
            prompts=self._uow.prompts.list_for_agent(agent_id, True),
        )
