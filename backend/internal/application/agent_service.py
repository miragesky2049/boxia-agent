"""智能体管理用例。"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.agent_visibility import (
    VISIBILITY_MODES,
    VISIBILITY_MODE_ALL,
    AgentVisibility,
)
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

    def get(self, agent_id: UUID) -> Agent:
        """查询详情。"""
        agent = self._uow.agents.get(agent_id)
        if agent is None:
            raise NotFoundError("智能体不存在")
        return agent

    def create(
        self,
        values: dict,
        actor_role_ids: Sequence[UUID] = (),
        actor_user_id: UUID | None = None,
    ) -> Agent:
        """创建智能体，并授权给创建者角色以保证创建者立即可见。"""
        if self._uow.agents.name_exists(values["name"]):
            raise ConflictError("智能体名称已存在")
        values = self._with_validated_relations(values)
        # 租户智能体记录创建者，供"本人数据"行级范围使用；平台智能体无归属
        if actor_user_id is not None and not self._context.is_platform:
            values["created_by"] = actor_user_id
        agent = self._uow.agents.create(values)
        self._grant_actor(agent, actor_role_ids)
        self._uow.commit()
        return agent

    def update(self, agent_id: UUID, values: dict) -> Agent:
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

    def delete(self, agent_id: UUID) -> None:
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

    def get_visibility(self, agent_id: UUID) -> AgentVisibility:
        """查询智能体 user 端可见范围配置。"""
        existing = self._uow.agents.get(agent_id)
        if existing is None:
            raise NotFoundError("智能体不存在")
        if existing.tenant_id is None:
            raise ValidationError("产品级智能体不配置 user 端可见范围")
        visibility = self._uow.agents.get_visibility(agent_id)
        if visibility is None:
            raise NotFoundError("智能体不存在")
        return visibility

    def save_visibility(
        self,
        agent_id: UUID,
        mode: str,
        departments: list[tuple[UUID, bool]],
        user_ids: list[UUID],
    ) -> AgentVisibility:
        """全量替换智能体 user 端可见范围；仅租户智能体可写。"""
        existing = self._uow.agents.get(agent_id)
        if existing is None:
            raise NotFoundError("智能体不存在")
        self._ensure_manageable(existing)
        if existing.tenant_id is None:
            raise ValidationError("产品级智能体不配置 user 端可见范围")
        if mode not in VISIBILITY_MODES:
            raise ValidationError(f"可见范围模式必须为 {VISIBILITY_MODES} 之一")

        # 校验部门与用户均属于当前租户
        unique_dept_ids = sorted({dept_id for dept_id, _ in departments})
        if unique_dept_ids:
            for dept_id in unique_dept_ids:
                department = self._uow.departments.get(dept_id)
                if department is None or department.tenant_id != existing.tenant_id:
                    raise ValidationError(f"可见部门不存在或不属于当前租户：{dept_id}")
        unique_user_ids = sorted(set(user_ids))
        if unique_user_ids:
            existing_users = self._uow.users.ids_existing(
                existing.tenant_id, unique_user_ids
            )
            missing = set(unique_user_ids) - existing_users
            if missing:
                raise ValidationError(f"可见用户不存在或不属于当前租户：{sorted(missing)}")

        # all 模式下忽略部门/人员列表，避免脏数据
        normalized_departments = departments if mode != VISIBILITY_MODE_ALL else []
        normalized_user_ids = unique_user_ids if mode != VISIBILITY_MODE_ALL else []

        saved = self._uow.agents.replace_visibility(
            agent_id, mode, normalized_departments, normalized_user_ids
        )
        if saved is None:
            raise NotFoundError("智能体不存在")
        self._uow.commit()
        return saved

    def _grant_actor(self, agent: Agent, actor_role_ids: Sequence[UUID]) -> None:
        """把租户自有智能体授权给创建者角色；平台智能体不自动授权。"""
        tenant_id = getattr(agent, "tenant_id", None)
        role_ids = sorted(set(actor_role_ids))
        if tenant_id is None or not role_ids:
            return
        for role_id in role_ids:
            self._uow.resource_grants.add_for_role(role_id, tenant_id, "agent", [agent.id], None)

    def _ensure_manageable(self, agent: Agent) -> None:
        """校验当前作用域是否有权维护该智能体。"""
        if not self._context.can_manage(agent.tenant_id):
            raise ForbiddenError("该智能体属于产品级资源，仅产品级运营管理平台可维护")

    def _with_validated_relations(self, values: dict) -> dict:
        """校验关联的工具/技能存在，并去重。"""
        payload = dict(values)
        tool_ids = sorted({UUID(str(item)) for item in payload.get("tool_ids", [])})
        skill_ids = sorted({UUID(str(item)) for item in payload.get("skill_ids", [])})

        missing_tools = set(tool_ids) - self._uow.tools.ids_exist(tool_ids)
        if missing_tools:
            raise ValidationError(f"工具不存在：{sorted(missing_tools)}")

        missing_skills = set(skill_ids) - self._uow.skills.ids_exist(skill_ids)
        if missing_skills:
            raise ValidationError(f"技能不存在：{sorted(missing_skills)}")

        payload["tool_ids"] = tool_ids
        payload["skill_ids"] = skill_ids
        payload["department_id"] = self._validated_department(
            payload.get("department_id")
        )
        return payload

    def _validated_department(self, value: object) -> UUID | None:
        """平台智能体强制无部门；租户智能体必填且校验同租户启用。"""
        department_id = UUID(str(value)) if value else None
        if self._context.is_platform:
            if department_id is not None:
                raise ValidationError("产品级智能体不能归属部门")
            return None
        if department_id is None:
            # 租户智能体所属部门必填：行级数据权限（按部门过滤）依赖该列
            raise ValidationError("租户智能体必须选择所属部门")
        department = self._uow.departments.get(department_id)
        if department is None or department.tenant_id != self._context.tenant_id:
            raise ValidationError("所属部门不存在或不属于当前租户")
        if not department.is_active:
            raise ValidationError("所属部门已停用，不能挂接智能体")
        return department_id
