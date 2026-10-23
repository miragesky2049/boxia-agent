"""技能、工具、组件、提示词的 PostgreSQL 仓储实现。"""

from typing import Any, Generic, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from internal.infrastructure.model.resource import (
    ComponentModel,
    PromptModel,
    SkillModel,
    ToolModel,
)

TResource = TypeVar("TResource")


class PostgresResourceRepository(Generic[TResource]):
    """通用资源仓储基类。"""

    model: type[Any]

    def __init__(self, session: Session, tenant_id: int | None = None):
        self._session = session
        self._tenant_id = tenant_id

    def _to_entity(self, row: Any) -> TResource:
        raise NotImplementedError

    def _visible(self, stmt):
        """读可见范围：租户可见本租户资源 + 产品级资源；产品级只可见产品级。"""
        if self._tenant_id is None:
            return stmt.where(self.model.tenant_id.is_(None))
        return stmt.where(
            or_(self.model.tenant_id == self._tenant_id, self.model.tenant_id.is_(None))
        )

    def _owned(self, stmt):
        """写归属范围：只能维护当前作用域自有的资源。"""
        if self._tenant_id is None:
            return stmt.where(self.model.tenant_id.is_(None))
        return stmt.where(self.model.tenant_id == self._tenant_id)

    def _get_owned(self, resource_id: int) -> Any | None:
        row = self._session.get(self.model, resource_id)
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
    ) -> tuple[list[TResource], int]:
        """分页查询，关键字模糊匹配名称与描述。"""
        stmt = self._visible(select(self.model))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(self.model.name.ilike(pattern), self.model.description.ilike(pattern))
            )
        if is_enabled is not None:
            stmt = stmt.where(self.model.is_enabled.is_(is_enabled))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(self.model.updated_at.desc(), self.model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def get(self, resource_id: int) -> TResource | None:
        """按主键查询（限定可见范围）。"""
        row = self._session.scalar(
            self._visible(select(self.model)).where(self.model.id == resource_id)
        )
        return self._to_entity(row) if row else None

    def create(self, values: dict[str, Any]) -> TResource:
        """创建记录（提交由 UnitOfWork 负责），归属当前作用域。"""
        payload = dict(values)
        payload["tenant_id"] = self._tenant_id
        row = self.model(**payload)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, resource_id: int, values: dict[str, Any]) -> TResource | None:
        """更新当前作用域自有的记录（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, resource_id: int) -> bool:
        """删除当前作用域自有的记录（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """名称在当前归属范围内是否已被占用（忽略大小写）。"""
        stmt = self._owned(select(self.model.id)).where(
            func.lower(self.model.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(self.model.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def get_by_name(self, name: str) -> TResource | None:
        """按名称在当前归属范围内精确查询（忽略大小写）。"""
        row = self._session.scalar(
            self._owned(select(self.model)).where(
                func.lower(self.model.name) == name.strip().lower()
            )
        )
        return self._to_entity(row) if row else None

    def ids_exist(self, ids: list[int]) -> set[int]:
        """返回可见范围内真实存在的 id 集合。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._visible(select(self.model.id)).where(self.model.id.in_(ids))
        ).all()
        return {int(item) for item in rows}


class PostgresSkillRepository(PostgresResourceRepository[Skill]):
    """技能仓储。"""

    model = SkillModel

    def _to_entity(self, row: SkillModel) -> Skill:
        return Skill(
            id=row.id,
            name=row.name,
            description=row.description,
            content=row.content,
            config=row.config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
        )


class PostgresToolRepository(PostgresResourceRepository[Tool]):
    """工具仓储。"""

    model = ToolModel

    def _to_entity(self, row: ToolModel) -> Tool:
        return Tool(
            id=row.id,
            name=row.name,
            description=row.description,
            type=row.type,
            config=row.config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
        )


class PostgresComponentRepository(PostgresResourceRepository[Component]):
    """组件仓储。"""

    model = ComponentModel

    def _to_entity(self, row: ComponentModel) -> Component:
        return Component(
            id=row.id,
            name=row.name,
            description=row.description,
            type=row.type,
            config=row.config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
        )


class PostgresPromptRepository(PostgresResourceRepository[Prompt]):
    """提示词仓储。"""

    model = PromptModel

    def _to_entity(self, row: PromptModel) -> Prompt:
        return Prompt(
            id=row.id,
            name=row.name,
            description=row.description,
            content=row.content,
            variables=row.variables,
            category=row.category,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
        )
