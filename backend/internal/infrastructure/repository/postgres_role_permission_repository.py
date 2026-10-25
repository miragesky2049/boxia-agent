"""角色权限关系的 PostgreSQL 仓储实现。"""

from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.infrastructure.model.access import (
    PermissionResourceModel,
    RoleModel,
    RolePermissionModel,
)


class PostgresRolePermissionRepository:
    """基于 SQLAlchemy 的角色权限仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def lock_role(self, role_id: int) -> bool:
        """锁定角色行，串行化同一角色的并发授权写入。"""
        row = self._session.scalar(
            select(RoleModel.id).where(RoleModel.id == role_id).with_for_update()
        )
        return row is not None

    def list_codes_for_role(self, role_id: int) -> set[str]:
        """读取角色已授予的权限编码。"""
        rows = self._session.scalars(
            select(PermissionResourceModel.code)
            .join(
                RolePermissionModel,
                RolePermissionModel.permission_id == PermissionResourceModel.id,
            )
            .where(RolePermissionModel.role_id == role_id)
        ).all()
        return {str(code) for code in rows}

    def list_codes_for_roles(self, role_ids: tuple[int, ...]) -> set[str]:
        """合并读取多个角色的权限编码。"""
        if not role_ids:
            return set()
        rows = self._session.scalars(
            select(PermissionResourceModel.code)
            .join(
                RolePermissionModel,
                RolePermissionModel.permission_id == PermissionResourceModel.id,
            )
            .where(RolePermissionModel.role_id.in_(role_ids))
        ).all()
        return {str(code) for code in rows}

    def list_role_ids_with_code(self, tenant_id: int | None, code: str) -> set[int]:
        """读取作用域内拥有指定权限的角色 ID。"""
        stmt = (
            select(RolePermissionModel.role_id)
            .join(RoleModel, RoleModel.id == RolePermissionModel.role_id)
            .join(
                PermissionResourceModel,
                PermissionResourceModel.id == RolePermissionModel.permission_id,
            )
            .where(PermissionResourceModel.code == code)
        )
        if tenant_id is None:
            stmt = stmt.where(RoleModel.tenant_id.is_(None))
        else:
            stmt = stmt.where(RoleModel.tenant_id == tenant_id)
        rows = self._session.scalars(stmt).all()
        return {int(role_id) for role_id in rows}

    def replace_for_role(
        self, role_id: int, codes: set[str] | frozenset[str], granted_by: int | None
    ) -> None:
        """整体替换角色权限；未在目录中的编码被忽略。"""
        permission_ids = self._permission_ids(codes)
        self._session.execute(
            delete(RolePermissionModel).where(RolePermissionModel.role_id == role_id)
        )
        if permission_ids:
            self._session.execute(
                pg_insert(RolePermissionModel).values(
                    [
                        {
                            "role_id": role_id,
                            "permission_id": permission_id,
                            "granted_by": granted_by,
                        }
                        for permission_id in permission_ids
                    ]
                )
            )
        self._session.flush()

    def add_for_role(
        self, role_id: int, codes: set[str] | frozenset[str], granted_by: int | None
    ) -> int:
        """追加角色权限，重复授权自动跳过。"""
        permission_ids = self._permission_ids(codes)
        if not permission_ids:
            return 0
        stmt = (
            pg_insert(RolePermissionModel)
            .values(
                [
                    {
                        "role_id": role_id,
                        "permission_id": permission_id,
                        "granted_by": granted_by,
                    }
                    for permission_id in permission_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )
        result = cast(CursorResult, self._session.execute(stmt))
        self._session.flush()
        return int(result.rowcount or 0)

    def remove_for_role(self, role_id: int, code: str) -> bool:
        """移除角色对单个权限的授权。"""
        permission_id = self._session.scalar(
            select(PermissionResourceModel.id).where(PermissionResourceModel.code == code)
        )
        if permission_id is None:
            return False
        result = cast(
            CursorResult,
            self._session.execute(
                delete(RolePermissionModel).where(
                    RolePermissionModel.role_id == role_id,
                    RolePermissionModel.permission_id == permission_id,
                )
            ),
        )
        self._session.flush()
        return int(result.rowcount or 0) > 0

    def count_for_role(self, role_id: int) -> int:
        """统计角色权限数量。"""
        total = self._session.scalar(
            select(func.count())
            .select_from(RolePermissionModel)
            .where(RolePermissionModel.role_id == role_id)
        )
        return int(total or 0)

    def _permission_ids(self, codes: set[str] | frozenset[str]) -> list[int]:
        if not codes:
            return []
        rows = self._session.scalars(
            select(PermissionResourceModel.id)
            .where(
                PermissionResourceModel.code.in_(sorted(codes)),
                PermissionResourceModel.is_active.is_(True),
            )
            .order_by(PermissionResourceModel.id.asc())
        ).all()
        return [int(item) for item in rows]
