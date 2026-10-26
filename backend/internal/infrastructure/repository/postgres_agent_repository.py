"""智能体的 PostgreSQL 仓储实现。"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.resource import Agent
from internal.infrastructure.model.agent import AgentModel, agent_skills, agent_tools
from internal.infrastructure.model.resource import SkillModel, ToolModel
from internal.infrastructure.repository.grant_filters import (
    agent_visible,
    has_any_grant,
    platform_role_grant_exists,
    tenant_grant_exists,
)


class PostgresAgentRepository:
    """基于 SQLAlchemy 的智能体仓储。"""

    def __init__(
        self,
        session: Session,
        tenant_id: UUID | None = None,
        role_ids: tuple[UUID, ...] = (),
        apply_role_filter: bool = True,
        department_scope: frozenset[UUID] | None = None,
    ):
        self._session = session
        self._tenant_id = tenant_id
        self._role_ids = tuple(role_ids)
        self._apply_role_filter = apply_role_filter
        # 部门数据范围预留接入点：非 None 时仅该集合内部门的租户智能体可见，
        # 未分配部门的租户智能体 fail-closed；本期不接线（apply_scope 不传），行为不变。
        self._department_scope = department_scope

    def _visible(self, stmt):
        """读可见范围：平台视角仅产品级，非超管按平台角色授权过滤；租户视角按授权过滤。"""
        if self._tenant_id is None:
            stmt = stmt.where(AgentModel.tenant_id.is_(None))
            if self._apply_role_filter:
                stmt = stmt.where(
                    platform_role_grant_exists("agent", AgentModel.id, self._role_ids)
                )
            return stmt
        stmt = stmt.where(
            agent_visible(
                AgentModel.id,
                self._tenant_id,
                self._role_ids,
                self._apply_role_filter,
            )
        )
        if self._department_scope is not None:
            stmt = stmt.where(
                or_(
                    AgentModel.tenant_id.is_(None),
                    and_(
                        AgentModel.tenant_id == self._tenant_id,
                        AgentModel.department_id.in_(self._department_scope),
                    ),
                )
            )
        return stmt

    def _owned(self, stmt):
        """写归属范围。"""
        if self._tenant_id is None:
            return stmt.where(AgentModel.tenant_id.is_(None))
        return stmt.where(AgentModel.tenant_id == self._tenant_id)

    def _owned_row(self, agent_id: UUID) -> AgentModel | None:
        row = self._session.get(AgentModel, agent_id)
        if row is None:
            return None
        if self._tenant_id is None:
            return row if row.tenant_id is None else None
        return row if row.tenant_id == self._tenant_id else None

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[Agent], int]:
        """分页查询（列表不加载关联 id）。

        manageable_only 仅返回当前作用域可授权的智能体；grant_state 按直接授权记录筛选。
        """
        stmt = (
            self._owned(select(AgentModel))
            if manageable_only
            else self._visible(select(AgentModel))
        )
        if grant_state is not None:
            condition = (
                has_any_grant("agent", AgentModel.id)
                if grant_tenant_id is None
                else tenant_grant_exists("agent", AgentModel.id, grant_tenant_id)
            )
            stmt = stmt.where(condition if grant_state == "granted" else ~condition)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(AgentModel.name.ilike(pattern), AgentModel.description.ilike(pattern))
            )
        if is_enabled is not None:
            stmt = stmt.where(AgentModel.is_enabled.is_(is_enabled))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(AgentModel.updated_at.desc(), AgentModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def get(self, agent_id: UUID) -> Agent | None:
        """查询详情（含工具/技能关联，限定可见范围）。"""
        row = self._session.scalar(
            self._visible(select(AgentModel)).where(AgentModel.id == agent_id)
        )
        if row is None:
            return None
        return self._to_entity(row, self._tool_ids(agent_id), self._skill_ids(agent_id))

    def create(self, values: dict[str, Any]) -> Agent:
        """创建智能体并在同一事务内写入关联，归属当前作用域。"""
        payload = dict(values)
        payload["tenant_id"] = self._tenant_id
        tool_ids = _unique_ids(payload.pop("tool_ids", []))
        skill_ids = _unique_ids(payload.pop("skill_ids", []))

        row = AgentModel(**payload)
        self._session.add(row)
        self._session.flush()
        self._replace_relations(row.id, tool_ids, skill_ids)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row, tool_ids, skill_ids)

    def update(self, agent_id: UUID, values: dict[str, Any]) -> Agent | None:
        """全量更新并替换关联，仅限当前作用域自有智能体。"""
        row = self._owned_row(agent_id)
        if row is None:
            return None

        payload = dict(values)
        tool_ids = _unique_ids(payload.pop("tool_ids", []))
        skill_ids = _unique_ids(payload.pop("skill_ids", []))
        for key, value in payload.items():
            setattr(row, key, value)
        self._session.flush()
        self._replace_relations(agent_id, tool_ids, skill_ids)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row, self._tool_ids(agent_id), self._skill_ids(agent_id))

    def delete(self, agent_id: UUID) -> bool:
        """删除当前作用域自有的智能体（关联表由外键级联删除）。"""
        row = self._owned_row(agent_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def ids_owned(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._owned(select(AgentModel.id)).where(AgentModel.id.in_(ids))
        ).all()
        return set(rows)

    def _grantable(self, stmt):
        """角色授权候选范围：租户自有智能体 + 已对本租户可见的平台智能体。"""
        if self._tenant_id is None:
            return stmt.where(AgentModel.tenant_id.is_(None))
        tenant_owned = AgentModel.tenant_id == self._tenant_id
        platform_entitled = and_(
            AgentModel.tenant_id.is_(None),
            agent_visible(AgentModel.id, self._tenant_id, (), False),
        )
        return stmt.where(or_(tenant_owned, platform_entitled))

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[Agent], int]:
        """分页查询可向本租户角色授权的智能体。"""
        stmt = self._grantable(select(AgentModel))
        if ids is not None:
            if not ids:
                return [], 0
            stmt = stmt.where(AgentModel.id.in_(ids))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(AgentModel.name.ilike(pattern), AgentModel.description.ilike(pattern))
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(AgentModel.updated_at.desc(), AgentModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中可向本租户角色授权的部分。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._grantable(select(AgentModel.id)).where(AgentModel.id.in_(ids))
        ).all()
        return set(rows)

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """名称在当前归属范围内是否已被占用（忽略大小写）。"""
        stmt = self._owned(select(AgentModel.id)).where(
            func.lower(AgentModel.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(AgentModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def _relation_ids(self, table, column_name: str, agent_id: UUID) -> list[UUID]:
        rows = self._session.scalars(
            select(table.c[column_name]).where(table.c.agent_id == agent_id)
        ).all()
        return list(rows)

    def _tool_ids(self, agent_id: UUID) -> list[UUID]:
        """合并旧关联表与 agent_id 归属的工具。"""
        legacy = set(self._relation_ids(agent_tools, "tool_id", agent_id))
        owned = self._session.scalars(
            select(ToolModel.id).where(ToolModel.agent_id == agent_id)
        ).all()
        return sorted(legacy | set(owned))

    def _skill_ids(self, agent_id: UUID) -> list[UUID]:
        """合并旧关联表与 agent_id 归属的技能。"""
        legacy = set(self._relation_ids(agent_skills, "skill_id", agent_id))
        owned = self._session.scalars(
            select(SkillModel.id).where(SkillModel.agent_id == agent_id)
        ).all()
        return sorted(legacy | set(owned))

    def _replace_relations(
        self, agent_id: UUID, tool_ids: list[UUID], skill_ids: list[UUID]
    ) -> None:
        self._session.execute(delete(agent_tools).where(agent_tools.c.agent_id == agent_id))
        self._session.execute(delete(agent_skills).where(agent_skills.c.agent_id == agent_id))
        if tool_ids:
            self._session.execute(
                insert(agent_tools),
                [{"agent_id": agent_id, "tool_id": tool_id} for tool_id in tool_ids],
            )
        if skill_ids:
            self._session.execute(
                insert(agent_skills),
                [{"agent_id": agent_id, "skill_id": skill_id} for skill_id in skill_ids],
            )

    @staticmethod
    def _to_entity(
        row: AgentModel, tool_ids: list[UUID] | None = None, skill_ids: list[UUID] | None = None
    ) -> Agent:
        return Agent(
            id=row.id,
            name=row.name,
            avatar_url=row.avatar_url,
            description=row.description,
            config=row.config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tool_ids=tool_ids or [],
            skill_ids=skill_ids or [],
            tenant_id=row.tenant_id,
            department_id=row.department_id,
        )


def _unique_ids(values: list[UUID]) -> list[UUID]:
    return sorted(set(values))
