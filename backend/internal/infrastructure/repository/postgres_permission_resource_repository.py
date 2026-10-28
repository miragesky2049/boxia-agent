"""权限资源目录的 PostgreSQL 仓储实现。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from internal.domain.entity.permission import PermissionResource
from internal.infrastructure.model.access import PermissionResourceModel


class PostgresPermissionResourceRepository:
    """基于 SQLAlchemy 的权限目录仓储，仅提供只读查询。"""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self, include_inactive: bool = False) -> list[PermissionResource]:
        """按分类与排序读取权限目录。"""
        stmt = select(PermissionResourceModel)
        if not include_inactive:
            stmt = stmt.where(PermissionResourceModel.is_active.is_(True))
        rows = self._session.scalars(
            stmt.order_by(
                PermissionResourceModel.category.asc(),
                PermissionResourceModel.sort_order.asc(),
                PermissionResourceModel.id.asc(),
            )
        ).all()
        return [self._to_entity(row) for row in rows]

    def list_by_codes(self, codes: set[str] | frozenset[str]) -> list[PermissionResource]:
        """按编码批量读取权限资源。"""
        if not codes:
            return []
        rows = self._session.scalars(
            select(PermissionResourceModel)
            .where(PermissionResourceModel.code.in_(sorted(codes)))
            .order_by(PermissionResourceModel.sort_order.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def list_ids_by_codes(self, codes: set[str] | frozenset[str]) -> dict[str, UUID]:
        """返回编码到主键的映射。"""
        if not codes:
            return {}
        rows = self._session.execute(
            select(PermissionResourceModel.code, PermissionResourceModel.id).where(
                PermissionResourceModel.code.in_(sorted(codes)),
                PermissionResourceModel.is_active.is_(True),
            )
        ).all()
        return {str(code): permission_id for code, permission_id in rows}

    def existing_codes(self, codes: set[str] | frozenset[str]) -> set[str]:
        """返回给定编码中真实存在且启用的部分。"""
        if not codes:
            return set()
        rows = self._session.scalars(
            select(PermissionResourceModel.code).where(
                PermissionResourceModel.code.in_(sorted(codes)),
                PermissionResourceModel.is_active.is_(True),
            )
        ).all()
        return {str(code) for code in rows}

    @staticmethod
    def _to_entity(row: PermissionResourceModel) -> PermissionResource:
        return PermissionResource(
            id=row.id,
            code=row.code,
            name=row.name,
            category=row.category,
            action=row.action,
            description=row.description,
            sort_order=row.sort_order,
            is_active=row.is_active,
        )
