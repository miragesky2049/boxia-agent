"""技能、工具、组件、提示词的 PostgreSQL 仓储实现。"""

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from internal.infrastructure.model.resource import (
    ComponentModel,
    PromptModel,
    SkillModel,
    ToolModel,
)
from internal.infrastructure.repository.grant_filters import (
    has_any_grant,
    platform_resource_visible,
    platform_role_grant_exists,
    tenant_grant_exists,
    tenant_resource_visible,
)

TResource = TypeVar("TResource")


class PostgresResourceRepository(Generic[TResource]):
    """通用资源仓储基类。"""

    model: type[Any]
    resource_type: str

    def __init__(
        self,
        session: Session,
        tenant_id: UUID | None = None,
        role_ids: tuple[UUID, ...] = (),
        apply_role_filter: bool = True,
    ):
        self._session = session
        # None 归一化为 PLATFORM_TENANT_ID，消除所有 Optional 分支
        self._tenant_id: UUID = tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
        self._role_ids = tuple(role_ids)
        self._apply_role_filter = apply_role_filter

    def _to_entity(self, row: Any) -> TResource:
        raise NotImplementedError

    def _visible(self, stmt):
        """读可见范围：平台视角仅产品级，非超管按平台角色授权过滤；租户视角按归属与授权过滤。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            stmt = stmt.where(self.model.tenant_id == PLATFORM_TENANT_ID)
            if self._apply_role_filter:
                stmt = stmt.where(
                    platform_role_grant_exists(self.resource_type, self.model.id, self._role_ids)
                )
            return stmt
        tenant_owned = and_(
            self.model.tenant_id == self._tenant_id,
            tenant_resource_visible(
                self.resource_type,
                self.model.id,
                self._tenant_id,
                self._role_ids,
                self._apply_role_filter,
            ),
        )
        platform_resource = and_(
            self.model.tenant_id == PLATFORM_TENANT_ID,
            platform_resource_visible(
                self.resource_type,
                self.model.id,
                self.model.agent_id,
                self._tenant_id,
                self._role_ids,
                self._apply_role_filter,
            ),
        )
        return stmt.where(or_(tenant_owned, platform_resource))

    def _owned(self, stmt):
        """写归属范围：只能维护当前作用域自有的资源。"""
        return stmt.where(self.model.tenant_id == self._tenant_id)

    def _get_owned(self, resource_id: UUID) -> Any | None:
        row = self._session.get(self.model, resource_id)
        if row is None:
            return None
        return row if row.tenant_id == self._tenant_id else None

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        agent_id: UUID | None = None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询，关键字模糊匹配名称与描述。

        manageable_only 仅返回当前作用域可授权的资源；grant_state 按直接授权记录筛选。
        """
        stmt = (
            self._owned(select(self.model))
            if manageable_only
            else self._visible(select(self.model))
        )
        if grant_state is not None:
            condition = (
                has_any_grant(self.resource_type, self.model.id)
                if grant_tenant_id is None
                else tenant_grant_exists(self.resource_type, self.model.id, grant_tenant_id)
            )
            stmt = stmt.where(condition if grant_state == "granted" else ~condition)
        if agent_id is not None:
            stmt = stmt.where(self.model.agent_id == agent_id)
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

    def get(self, resource_id: UUID) -> TResource | None:
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

    def update(self, resource_id: UUID, values: dict[str, Any]) -> TResource | None:
        """更新当前作用域自有的记录（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, resource_id: UUID) -> bool:
        """删除当前作用域自有的记录（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
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

    def list_for_agent(self, agent_id: UUID, is_enabled: bool | None = None) -> list[TResource]:
        """读取归属于指定智能体的可见资源（用户端运行时使用）。"""
        stmt = self._visible(select(self.model)).where(self.model.agent_id == agent_id)
        if is_enabled is not None:
            stmt = stmt.where(self.model.is_enabled.is_(is_enabled))
        rows = self._session.scalars(stmt.order_by(self.model.id.asc())).all()
        return [self._to_entity(row) for row in rows]

    def ids_exist(self, ids: list[UUID], agent_id: UUID | None = None) -> set[UUID]:
        """返回可见范围内真实存在的 id 集合。"""
        if not ids:
            return set()
        stmt = self._visible(select(self.model.id)).where(self.model.id.in_(ids))
        if agent_id is not None:
            stmt = stmt.where(self.model.agent_id == agent_id)
        rows = self._session.scalars(stmt).all()
        return set(rows)

    def ids_owned(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._owned(select(self.model.id)).where(self.model.id.in_(ids))
        ).all()
        return set(rows)

    def list_ids_for_agent(self, agent_id: UUID) -> list[UUID]:
        """按归属读取智能体下的全部资源 ID，忽略角色可见性过滤。"""
        rows = self._session.scalars(
            self._owned(select(self.model.id)).where(self.model.agent_id == agent_id)
        ).all()
        return list(rows)

    def _grantable(self, stmt):
        """角色授权候选范围：租户自有资源 + 已对本租户可见的平台资源。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            return stmt.where(self.model.tenant_id == PLATFORM_TENANT_ID)
        tenant_owned = self.model.tenant_id == self._tenant_id
        platform_entitled = and_(
            self.model.tenant_id == PLATFORM_TENANT_ID,
            platform_resource_visible(
                self.resource_type,
                self.model.id,
                self.model.agent_id,
                self._tenant_id,
                (),
                False,
            ),
        )
        return stmt.where(or_(tenant_owned, platform_entitled))

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询可向本租户角色授权的资源。"""
        stmt = self._grantable(select(self.model))
        if ids is not None:
            if not ids:
                return [], 0
            stmt = stmt.where(self.model.id.in_(ids))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(self.model.name.ilike(pattern), self.model.description.ilike(pattern))
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(self.model.updated_at.desc(), self.model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中可向本租户角色授权的部分。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._grantable(select(self.model.id)).where(self.model.id.in_(ids))
        ).all()
        return set(rows)


class PostgresSkillRepository(PostgresResourceRepository[Skill]):
    """技能仓储。"""

    model = SkillModel
    resource_type = "skill"

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
            agent_id=row.agent_id,
        )


class PostgresToolRepository(PostgresResourceRepository[Tool]):
    """工具仓储。"""

    model = ToolModel
    resource_type = "tool"

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
            agent_id=row.agent_id,
        )


class PostgresComponentRepository(PostgresResourceRepository[Component]):
    """组件仓储。"""

    model = ComponentModel
    resource_type = "component"

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
            agent_id=row.agent_id,
        )


class PostgresPromptRepository(PostgresResourceRepository[Prompt]):
    """提示词仓储。"""

    model = PromptModel
    resource_type = "prompt"

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
            agent_id=row.agent_id,
        )
