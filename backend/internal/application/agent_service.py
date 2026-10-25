"""智能体管理用例。"""

from __future__ import annotations

from collections.abc import Sequence

from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.resource import Agent
from internal.domain.repository.protocols import UnitOfWork


class AgentService:
    """智能体 CRUD 与工具/技能关联校验。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> Page[Agent]:
        """分页查询智能体。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.agents.list_page(page, page_size, keyword, is_enabled)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get(self, agent_id: int) -> Agent:
        """查询详情。"""
        agent = self._uow.agents.get(agent_id)
        if agent is None:
            raise NotFoundError("智能体不存在")
        return agent

    def create(self, values: dict, actor_role_ids: Sequence[int] = ()) -> Agent:
        """创建智能体，并授权给创建者角色以保证创建者立即可见。"""
        if self._uow.agents.name_exists(values["name"]):
            raise ConflictError("智能体名称已存在")
        values = self._with_validated_relations(values)
        agent = self._uow.agents.create(values)
        self._grant_actor(agent, actor_role_ids)
        self._uow.commit()
        return agent

    def update(self, agent_id: int, values: dict) -> Agent:
        """更新智能体；产品级智能体仅产品级平台可维护。"""
        existing = self._uow.agents.get(agent_id)
        if existing is None:
            raise NotFoundError("智能体不存在")
        self._ensure_manageable(existing)
        if self._uow.agents.name_exists(values["name"], exclude_id=agent_id):
            raise ConflictError("智能体名称已存在")
        values = self._with_validated_relations(values)
        updated = self._uow.agents.update(agent_id, values)
        if updated is None:
            raise NotFoundError("智能体不存在")
        self._uow.commit()
        return updated

    def delete(self, agent_id: int) -> None:
        """删除智能体；产品级智能体仅产品级平台可维护。"""
        existing = self._uow.agents.get(agent_id)
        if existing is None:
            raise NotFoundError("智能体不存在")
        self._ensure_manageable(existing)
        resource_repositories = (
            ("skill", self._uow.skills),
            ("tool", self._uow.tools),
            ("component", self._uow.components),
            ("prompt", self._uow.prompts),
        )
        for resource_type, repository in resource_repositories:
            resource_ids = repository.list_ids_for_agent(agent_id)
            if resource_ids:
                self._uow.resource_grants.delete_for_resources(resource_type, resource_ids)
        if not self._uow.agents.delete(agent_id):
            raise NotFoundError("智能体不存在")
        self._uow.resource_grants.delete_for_resource("agent", agent_id)
        self._uow.commit()

    def _grant_actor(self, agent: Agent, actor_role_ids: Sequence[int]) -> None:
        """把租户自有智能体授权给创建者角色；平台智能体不自动授权。"""
        tenant_id = getattr(agent, "tenant_id", None)
        role_ids = sorted({int(role_id) for role_id in actor_role_ids})
        if tenant_id is None or not role_ids:
            return
        for role_id in role_ids:
            self._uow.resource_grants.add_for_role(
                role_id, tenant_id, "agent", [agent.id], None
            )

    def _ensure_manageable(self, agent: Agent) -> None:
        """校验当前作用域是否有权维护该智能体。"""
        if not self._context.can_manage(agent.tenant_id):
            raise ForbiddenError("该智能体属于产品级资源，仅产品级运营管理平台可维护")

    def _with_validated_relations(self, values: dict) -> dict:
        """校验关联的工具/技能存在，并去重。"""
        payload = dict(values)
        tool_ids = sorted({int(item) for item in payload.get("tool_ids", [])})
        skill_ids = sorted({int(item) for item in payload.get("skill_ids", [])})

        missing_tools = set(tool_ids) - self._uow.tools.ids_exist(tool_ids)
        if missing_tools:
            raise ValidationError(f"工具不存在：{sorted(missing_tools)}")

        missing_skills = set(skill_ids) - self._uow.skills.ids_exist(skill_ids)
        if missing_skills:
            raise ValidationError(f"技能不存在：{sorted(missing_skills)}")

        payload["tool_ids"] = tool_ids
        payload["skill_ids"] = skill_ids
        return payload
