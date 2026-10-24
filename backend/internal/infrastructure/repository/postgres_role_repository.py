"""租户角色的 PostgreSQL 仓储实现。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from internal.domain.entity.access import Role
from internal.infrastructure.model.access import RoleModel, UserModel, UserRoleModel


class PostgresRoleRepository:
    """基于 SQLAlchemy 的角色仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, role_id: int) -> Role | None:
        """按主键查询。"""
        row = self._session.get(RoleModel, role_id)
        return self._to_entity(row) if row else None

    def get_by_code(self, tenant_id: int, code: str) -> Role | None:
        """按租户与编码查询（忽略大小写）。"""
        row = self._session.scalar(
            select(RoleModel).where(
                RoleModel.tenant_id == tenant_id,
                func.lower(RoleModel.code) == code.strip().lower(),
            )
        )
        return self._to_entity(row) if row else None

    def list_by_tenant(self, tenant_id: int, include_inactive: bool = False) -> list[Role]:
        """查询租户角色列表，系统角色排在前面。"""
        stmt = select(RoleModel).where(RoleModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(RoleModel.is_active.is_(True))
        rows = self._session.scalars(
            stmt.order_by(RoleModel.is_system.desc(), RoleModel.id.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def create(self, values: dict[str, Any]) -> Role:
        """创建角色。"""
        row = RoleModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, role_id: int, values: dict[str, Any]) -> Role | None:
        """更新角色。"""
        row = self._session.get(RoleModel, role_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, role_id: int) -> bool:
        """删除角色。"""
        row = self._session.get(RoleModel, role_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def code_exists(self, tenant_id: int, code: str, exclude_id: int | None = None) -> bool:
        """租户内编码是否已存在（忽略大小写）。"""
        stmt = select(RoleModel.id).where(
            RoleModel.tenant_id == tenant_id,
            func.lower(RoleModel.code) == code.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(RoleModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def name_exists(self, tenant_id: int, name: str, exclude_id: int | None = None) -> bool:
        """租户内名称是否已存在（忽略大小写）。"""
        stmt = select(RoleModel.id).where(
            RoleModel.tenant_id == tenant_id,
            func.lower(RoleModel.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(RoleModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def count_references(self, role_id: int) -> int:
        """统计用户主角色与用户角色关联的引用数。"""
        user_count = self._session.scalar(
            select(func.count()).select_from(UserModel).where(UserModel.role_id == role_id)
        )
        relation_count = self._session.scalar(
            select(func.count())
            .select_from(UserRoleModel)
            .where(UserRoleModel.role_id == role_id)
        )
        return int(user_count or 0) + int(relation_count or 0)

    @staticmethod
    def _to_entity(row: RoleModel) -> Role:
        return Role(
            id=row.id,
            tenant_id=row.tenant_id,
            code=row.code,
            name=row.name,
            description=row.description,
            system_role=row.system_role,
            is_system=row.is_system,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
