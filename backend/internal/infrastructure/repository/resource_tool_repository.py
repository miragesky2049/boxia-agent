"""基于统一 resource 表的工具仓储。

工具行固定为 resource.type='tool'；归属经 owner_type/owner_id 表示：
owner_type='platform' 为产品级工具，owner_type='tenant' 时 owner_id 为所属租户。
角色级数据授权继续走 resource_grants（复数）表，resource_type='tool'，
因迁移保留原 ID，历史授权记录仍然有效。
"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.resource import Tool
from internal.infrastructure.model.resource import ResourceModel
from internal.infrastructure.repository.grant_filters import (
    has_any_grant,
    platform_resource_visible,
    platform_role_grant_exists,
    tenant_grant_exists,
    tenant_resource_visible,
)

_RESOURCE_TYPE = "tool"


class ResourceToolRepository:
    """工具仓储：resource 表 + resource_grants 可见性，输出 Tool 实体。"""

    def __init__(
        self,
        session: Session,
        tenant_id: UUID | None = None,
        role_ids: tuple[UUID, ...] = (),
        apply_role_filter: bool = True,
    ):
        self._session = session
        self._tenant_id: UUID = tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
        self._role_ids = tuple(role_ids)
        self._apply_role_filter = apply_role_filter

    def _to_entity(self, row: ResourceModel) -> Tool:
        config = row.config or {}
        description = config.get("description", "")
        if row.owner_type == "platform":
            tenant_id = PLATFORM_TENANT_ID
        else:
            assert row.owner_id is not None
            tenant_id = row.owner_id
        return Tool(
            id=row.id,
            name=row.name,
            description=description or "",
            type=row.type,
            config=config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.created_at,
            tenant_id=tenant_id,
        )

    def _owned_filter(self) -> Any:
        """写归属：平台作用域仅产品级，租户作用域仅本租户自有。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            return and_(
                ResourceModel.type == _RESOURCE_TYPE,
                ResourceModel.owner_type == "platform",
            )
        return and_(
            ResourceModel.type == _RESOURCE_TYPE,
            ResourceModel.owner_type == "tenant",
            ResourceModel.owner_id == self._tenant_id,
        )

    def _owned(self, stmt):
        return stmt.where(self._owned_filter())

    def _visible(self, stmt):
        """读可见范围：语义与旧 tools 表仓储一致。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            stmt = stmt.where(
                ResourceModel.type == _RESOURCE_TYPE,
                ResourceModel.owner_type == "platform",
            )
            if self._apply_role_filter:
                stmt = stmt.where(
                    platform_role_grant_exists(
                        _RESOURCE_TYPE, ResourceModel.id, self._role_ids
                    )
                )
            return stmt
        tenant_owned = and_(
            ResourceModel.owner_type == "tenant",
            ResourceModel.owner_id == self._tenant_id,
            tenant_resource_visible(
                _RESOURCE_TYPE,
                ResourceModel.id,
                self._tenant_id,
                self._role_ids,
                self._apply_role_filter,
            ),
        )
        platform_resource = and_(
            ResourceModel.owner_type == "platform",
            platform_resource_visible(
                _RESOURCE_TYPE,
                ResourceModel.id,
                self._tenant_id,
                self._role_ids,
                self._apply_role_filter,
            ),
        )
        return stmt.where(
            ResourceModel.type == _RESOURCE_TYPE, or_(tenant_owned, platform_resource)
        )

    def _get_owned(self, resource_id: UUID) -> ResourceModel | None:
        row = self._session.get(ResourceModel, resource_id)
        if row is None or row.type != _RESOURCE_TYPE:
            return None
        if row.owner_type == "platform":
            return row if self._tenant_id == PLATFORM_TENANT_ID else None
        return row if row.owner_id == self._tenant_id else None

    def _keyword(self, stmt, pattern: str):
        """名称与 config.description 模糊匹配。"""
        return stmt.where(
            or_(
                ResourceModel.name.ilike(pattern),
                ResourceModel.config["description"].astext.ilike(pattern),
            )
        )

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[Tool], int]:
        """分页查询，关键字模糊匹配名称与描述。"""
        stmt = (
            self._owned(select(ResourceModel))
            if manageable_only
            else self._visible(select(ResourceModel))
        )
        if grant_state is not None:
            condition = (
                has_any_grant(_RESOURCE_TYPE, ResourceModel.id)
                if grant_tenant_id is None
                else tenant_grant_exists(
                    _RESOURCE_TYPE, ResourceModel.id, grant_tenant_id
                )
            )
            stmt = stmt.where(condition if grant_state == "granted" else ~condition)
        if keyword and keyword.strip():
            stmt = self._keyword(stmt, f"%{keyword.strip()}%")
        if is_enabled is not None:
            stmt = stmt.where(ResourceModel.is_enabled.is_(is_enabled))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(ResourceModel.created_at.desc(), ResourceModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def get(self, resource_id: UUID) -> Tool | None:
        """按主键查询（限定可见范围）。"""
        row = self._session.scalar(
            self._visible(select(ResourceModel)).where(ResourceModel.id == resource_id)
        )
        return self._to_entity(row) if row else None

    def create(self, values: dict[str, Any]) -> Tool:
        """创建工具（提交由 UnitOfWork 负责），归属当前作用域。"""
        payload = dict(values)
        config = dict(payload.get("config") or {})
        if payload.get("description"):
            config.setdefault("description", payload["description"])
        is_platform = self._tenant_id == PLATFORM_TENANT_ID
        row = ResourceModel(
            id=payload.get("id"),
            type=_RESOURCE_TYPE,
            owner_type="platform" if is_platform else "tenant",
            owner_id=None if is_platform else self._tenant_id,
            name=payload["name"],
            config=config,
            is_enabled=payload.get("is_enabled", True),
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, resource_id: UUID, values: dict[str, Any]) -> Tool | None:
        """更新当前作用域自有的工具（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return None
        config = dict(row.config or {})
        if "config" in values:
            config = dict(values["config"] or {})
        if values.get("description") is not None:
            config["description"] = values["description"]
        row.name = values.get("name", row.name)
        row.config = config
        if values.get("type") is not None:
            row.type = values["type"]
        if values.get("is_enabled") is not None:
            row.is_enabled = values["is_enabled"]
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, resource_id: UUID) -> bool:
        """删除当前作用域自有的工具（提交由 UnitOfWork 负责）。"""
        row = self._get_owned(resource_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """名称在当前归属范围内是否已被占用（忽略大小写）。"""
        stmt = self._owned(select(ResourceModel.id)).where(
            func.lower(ResourceModel.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(ResourceModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def get_by_name(self, name: str) -> Tool | None:
        """按名称在当前归属范围内精确查询（忽略大小写）。"""
        row = self._session.scalar(
            self._owned(select(ResourceModel)).where(
                func.lower(ResourceModel.name) == name.strip().lower()
            )
        )
        return self._to_entity(row) if row else None

    def ids_exist(self, ids: list[UUID]) -> set[UUID]:
        """返回可见范围内真实存在的 id 集合。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._visible(select(ResourceModel.id)).where(ResourceModel.id.in_(ids))
        ).all()
        return set(rows)

    def ids_owned(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._owned(select(ResourceModel.id)).where(ResourceModel.id.in_(ids))
        ).all()
        return set(rows)

    def _grantable(self, stmt):
        """角色授权候选范围：租户自有工具 + 已对本租户可见的平台工具。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            return stmt.where(
                ResourceModel.type == _RESOURCE_TYPE,
                ResourceModel.owner_type == "platform",
            )
        tenant_owned = and_(
            ResourceModel.owner_type == "tenant",
            ResourceModel.owner_id == self._tenant_id,
        )
        platform_entitled = and_(
            ResourceModel.owner_type == "platform",
            platform_resource_visible(
                _RESOURCE_TYPE,
                ResourceModel.id,
                self._tenant_id,
                (),
                False,
            ),
        )
        return stmt.where(
            ResourceModel.type == _RESOURCE_TYPE, or_(tenant_owned, platform_entitled)
        )

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[Tool], int]:
        """分页查询可向本租户角色授权的工具。"""
        stmt = self._grantable(select(ResourceModel))
        if ids is not None:
            if not ids:
                return [], 0
            stmt = stmt.where(ResourceModel.id.in_(ids))
        if keyword and keyword.strip():
            stmt = self._keyword(stmt, f"%{keyword.strip()}%")
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(ResourceModel.created_at.desc(), ResourceModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中可向本租户角色授权的部分。"""
        if not ids:
            return set()
        rows = self._session.scalars(
            self._grantable(select(ResourceModel.id)).where(ResourceModel.id.in_(ids))
        ).all()
        return set(rows)
