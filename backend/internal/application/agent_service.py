"""智能体管理用例。"""

from internal.application.errors import ConflictError, NotFoundError, ValidationError
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.common import Page
from internal.domain.entity.resource import Agent
from internal.domain.repository.protocols import UnitOfWork


class AgentService:
    """智能体 CRUD 与工具/技能关联校验。"""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> Page[Agent]:
        """分页查询。"""
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

    def create(self, values: dict) -> Agent:
        """创建智能体。"""
        if self._uow.agents.name_exists(values["name"]):
            raise ConflictError("智能体名称已存在")
        values = self._with_validated_relations(values)
        agent = self._uow.agents.create(values)
        self._uow.commit()
        return agent

    def update(self, agent_id: int, values: dict) -> Agent:
        """更新智能体。"""
        if self._uow.agents.get(agent_id) is None:
            raise NotFoundError("智能体不存在")
        if self._uow.agents.name_exists(values["name"], exclude_id=agent_id):
            raise ConflictError("智能体名称已存在")
        values = self._with_validated_relations(values)
        updated = self._uow.agents.update(agent_id, values)
        if updated is None:
            raise NotFoundError("智能体不存在")
        self._uow.commit()
        return updated

    def delete(self, agent_id: int) -> None:
        """删除智能体。"""
        if not self._uow.agents.delete(agent_id):
            raise NotFoundError("智能体不存在")
        self._uow.commit()

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
