"""智能体的 PostgreSQL 仓储实现。"""

from typing import Any

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.resource import Agent
from internal.infrastructure.model.agent import AgentModel, agent_skills, agent_tools


class PostgresAgentRepository:
    """基于 SQLAlchemy 的智能体仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> tuple[list[Agent], int]:
        """分页查询（列表不加载关联 id）。"""
        stmt = select(AgentModel)
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

    def get(self, agent_id: int) -> Agent | None:
        """查询详情（含工具/技能关联）。"""
        row = self._session.get(AgentModel, agent_id)
        if row is None:
            return None
        return self._to_entity(
            row,
            self._relation_ids(agent_tools, "tool_id", agent_id),
            self._relation_ids(agent_skills, "skill_id", agent_id),
        )

    def create(self, values: dict[str, Any]) -> Agent:
        """创建智能体并在同一事务内写入关联。"""
        payload = dict(values)
        tool_ids = _unique_ids(payload.pop("tool_ids", []))
        skill_ids = _unique_ids(payload.pop("skill_ids", []))

        row = AgentModel(**payload)
        self._session.add(row)
        self._session.flush()
        self._replace_relations(row.id, tool_ids, skill_ids)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row, tool_ids, skill_ids)

    def update(self, agent_id: int, values: dict[str, Any]) -> Agent | None:
        """全量更新并替换关联。"""
        row = self._session.get(AgentModel, agent_id)
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
        return self._to_entity(row, tool_ids, skill_ids)

    def delete(self, agent_id: int) -> bool:
        """删除智能体（关联表由外键级联删除）。"""
        row = self._session.get(AgentModel, agent_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """名称是否已被占用（忽略大小写）。"""
        stmt = select(AgentModel.id).where(func.lower(AgentModel.name) == name.strip().lower())
        if exclude_id is not None:
            stmt = stmt.where(AgentModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def _relation_ids(self, table, column_name: str, agent_id: int) -> list[int]:
        rows = self._session.scalars(
            select(table.c[column_name]).where(table.c.agent_id == agent_id)
        ).all()
        return [int(item) for item in rows]

    def _replace_relations(self, agent_id: int, tool_ids: list[int], skill_ids: list[int]) -> None:
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
        row: AgentModel, tool_ids: list[int] | None = None, skill_ids: list[int] | None = None
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
        )


def _unique_ids(values: list[int]) -> list[int]:
    return sorted({int(item) for item in values})
