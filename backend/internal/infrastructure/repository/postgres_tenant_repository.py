"""租户的 PostgreSQL 仓储实现。"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.tenant import Tenant
from internal.infrastructure.model.tenant import TenantModel


class PostgresTenantRepository:
    """基于 SQLAlchemy 的租户仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_code(self, code: str) -> Tenant | None:
        """按租户编码（子域名）查询。"""
        row = self._session.scalar(
            select(TenantModel).where(TenantModel.code == code.strip().lower())
        )
        return self._to_entity(row) if row else None

    def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """按主键查询。"""
        row = self._session.get(TenantModel, tenant_id)
        return self._to_entity(row) if row else None

    def list_all(self) -> list[Tenant]:
        """查询全部租户（产品级平台使用）。"""
        rows = self._session.scalars(
            select(TenantModel).order_by(TenantModel.created_at.asc(), TenantModel.id.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def list_active(self) -> list[Tenant]:
        """查询启用中的租户。"""
        rows = self._session.scalars(
            select(TenantModel)
            .where(TenantModel.is_active.is_(True))
            .order_by(TenantModel.name.asc(), TenantModel.id.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def create(self, values: dict[str, Any]) -> Tenant:
        """创建租户。"""
        row = TenantModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, tenant_id: UUID, values: dict[str, Any]) -> Tenant | None:
        """更新租户基础信息。"""
        row = self._session.get(TenantModel, tenant_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def code_exists(self, code: str) -> bool:
        """租户编码是否已存在。"""
        return self.get_by_code(code) is not None

    def name_exists(self, name: str) -> bool:
        """租户名称是否已存在（忽略大小写）。"""
        stmt = select(TenantModel.id).where(func.lower(TenantModel.name) == name.strip().lower())
        return self._session.scalar(stmt) is not None

    def search(self, keyword: str | None) -> list[Tenant]:
        """按关键字查询全部租户。"""
        stmt = select(TenantModel)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(TenantModel.code.ilike(pattern), TenantModel.name.ilike(pattern)))
        rows = self._session.scalars(
            stmt.order_by(TenantModel.created_at.asc(), TenantModel.id.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: TenantModel) -> Tenant:
        return Tenant(
            id=row.id,
            code=row.code,
            name=row.name,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
