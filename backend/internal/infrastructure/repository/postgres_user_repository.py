"""最终用户的 PostgreSQL 仓储实现。"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.entity.access import User
from internal.infrastructure.model.access import (
    PermissionResourceModel,
    RolePermissionModel,
    UserModel,
    UserRoleModel,
)


class PostgresUserRepository:
    """基于 SQLAlchemy 的最终用户仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_username(self, username: str, tenant_id: UUID) -> User | None:
        """按用户名与租户查询。"""
        row = self._session.scalar(
            select(UserModel).where(
                UserModel.username == username,
                UserModel.tenant_id == tenant_id,
            )
        )
        return self._load_one(row)

    def get_by_username_for_update(self, username: str, tenant_id: UUID) -> User | None:
        """按用户名与租户加行锁查询。"""
        row = self._session.scalar(
            select(UserModel)
            .where(
                UserModel.username == username,
                UserModel.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        return self._load_one(row)

    def get_by_id(self, user_id: UUID) -> User | None:
        """按主键查询。"""
        row = self._session.get(UserModel, user_id)
        return self._load_one(row)

    def list_page(
        self, page: int, page_size: int, keyword: str | None, tenant_id: UUID
    ) -> tuple[list[User], int]:
        """分页查询租户最终用户。"""
        stmt = select(UserModel).where(UserModel.tenant_id == tenant_id)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    UserModel.username.ilike(pattern),
                    UserModel.display_name.ilike(pattern),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(UserModel.created_at.desc(), UserModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return self._load_many(rows), int(total)

    def create(self, values: dict[str, Any]) -> User:
        """创建最终用户。"""
        row = UserModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, user_id: UUID, values: dict[str, Any]) -> User | None:
        """更新最终用户。"""
        row = self._session.get(UserModel, user_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, user_id: UUID) -> bool:
        """删除最终用户。"""
        row = self._session.get(UserModel, user_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def username_exists(
        self, tenant_id: UUID, username: str, exclude_id: UUID | None = None
    ) -> bool:
        """租户内用户名是否已存在。"""
        stmt = select(UserModel.id).where(
            UserModel.tenant_id == tenant_id,
            UserModel.username == username,
        )
        if exclude_id is not None:
            stmt = stmt.where(UserModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def mark_login_success(self, user_id: UUID) -> None:
        """登录成功：清零失败次数并记录最后登录时间。"""
        row = self._session.get(UserModel, user_id)
        if row is None:
            return
        row.failed_login_count = 0
        row.locked_until = None
        row.last_login_at = datetime.now(UTC)
        self._session.flush()

    def record_failed_login(
        self, user_id: UUID, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，达到阈值后锁定账号。"""
        row = self._session.get(UserModel, user_id, with_for_update=True)
        if row is None:
            return None
        row.failed_login_count += 1
        if row.failed_login_count >= max_attempts:
            row.locked_until = datetime.now(UTC) + timedelta(minutes=lock_minutes)
            row.failed_login_count = 0
        self._session.flush()
        return row.locked_until

    def update_password(
        self,
        user_id: UUID,
        password_hash: str,
        must_change_password: bool,
        changed_at: datetime,
    ) -> None:
        """更新密码、改密标记与时间，并递增令牌版本。"""
        row = self._session.get(UserModel, user_id)
        if row is None:
            return
        row.password_hash = password_hash
        row.must_change_password = must_change_password
        row.password_changed_at = changed_at
        row.token_version += 1
        self._session.flush()

    def bump_token_version(self, user_id: UUID) -> int:
        """递增令牌版本。"""
        row = self._session.get(UserModel, user_id)
        if row is None:
            return 0
        row.token_version += 1
        self._session.flush()
        return row.token_version

    def list_role_ids(self, user_id: UUID) -> tuple[UUID, ...]:
        """读取用户的全部角色 ID。"""
        rows = self._session.scalars(
            select(UserRoleModel.role_id)
            .where(UserRoleModel.user_id == user_id)
            .order_by(UserRoleModel.id.asc())
        ).all()
        return tuple(rows)

    def list_role_ids_for_users(self, user_ids: list[UUID]) -> dict[UUID, tuple[UUID, ...]]:
        """批量读取多个用户的角色 ID。"""
        if not user_ids:
            return {}
        rows = self._session.execute(
            select(UserRoleModel.user_id, UserRoleModel.role_id)
            .where(UserRoleModel.user_id.in_(user_ids))
            .order_by(UserRoleModel.id.asc())
        ).all()
        result: dict[UUID, list[UUID]] = {}
        for user_id, role_id in rows:
            result.setdefault(user_id, []).append(role_id)
        return {user_id: tuple(role_ids) for user_id, role_ids in result.items()}

    def replace_roles(self, user_id: UUID, tenant_id: UUID, role_ids: list[UUID]) -> None:
        """整体替换用户角色，并把首个角色设为主角色。"""
        unique_role_ids = sorted(set(role_ids))
        if not unique_role_ids:
            raise ValueError("用户至少需要一个角色")
        self._session.execute(delete(UserRoleModel).where(UserRoleModel.user_id == user_id))
        self._session.execute(
            pg_insert(UserRoleModel),
            [
                {"user_id": user_id, "role_id": role_id, "tenant_id": tenant_id}
                for role_id in unique_role_ids
            ],
        )
        row = self._session.get(UserModel, user_id)
        if row is not None:
            row.role_id = unique_role_ids[0]
        self._session.flush()

    def add_roles_for_users(
        self, user_ids: list[UUID], tenant_id: UUID, role_ids: list[UUID]
    ) -> int:
        """批量追加角色授权，已存在的关联自动跳过。"""
        unique_users = sorted(set(user_ids))
        unique_roles = sorted(set(role_ids))
        if not unique_users or not unique_roles:
            return 0
        stmt = (
            pg_insert(UserRoleModel)
            .values(
                [
                    {"user_id": user_id, "role_id": role_id, "tenant_id": tenant_id}
                    for user_id in unique_users
                    for role_id in unique_roles
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
        )
        result = cast(CursorResult, self._session.execute(stmt))
        self._session.flush()
        return int(result.rowcount or 0)

    def list_admin_page(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        permission_code: str,
    ) -> tuple[list[User], int]:
        """分页查询拥有指定管理权限的租户用户。"""
        admin_user_ids = (
            select(UserRoleModel.user_id)
            .join(RolePermissionModel, RolePermissionModel.role_id == UserRoleModel.role_id)
            .join(
                PermissionResourceModel,
                PermissionResourceModel.id == RolePermissionModel.permission_id,
            )
            .where(
                UserRoleModel.tenant_id == tenant_id,
                PermissionResourceModel.code == permission_code,
            )
        )
        stmt = select(UserModel).where(
            UserModel.tenant_id == tenant_id,
            UserModel.id.in_(admin_user_ids),
        )
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    UserModel.username.ilike(pattern),
                    UserModel.display_name.ilike(pattern),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(UserModel.created_at.desc(), UserModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return self._load_many(rows), int(total)

    def has_permission(self, user_id: UUID, tenant_id: UUID, permission_code: str) -> bool:
        """判断用户是否通过任一角色获得指定权限。"""
        row = self._session.scalar(
            select(UserRoleModel.id)
            .join(RolePermissionModel, RolePermissionModel.role_id == UserRoleModel.role_id)
            .join(
                PermissionResourceModel,
                PermissionResourceModel.id == RolePermissionModel.permission_id,
            )
            .where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.tenant_id == tenant_id,
                PermissionResourceModel.code == permission_code,
            )
            .limit(1)
        )
        return row is not None

    def ids_existing(self, tenant_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中属于当前租户的用户 ID。"""
        if not user_ids:
            return set()
        rows = self._session.scalars(
            select(UserModel.id).where(
                UserModel.tenant_id == tenant_id,
                UserModel.id.in_(user_ids),
            )
        ).all()
        return set(rows)

    def _load_one(self, row: UserModel | None) -> User | None:
        if row is None:
            return None
        return self._load_many([row])[0]

    def _load_many(self, rows: Sequence[UserModel]) -> list[User]:
        """批量补齐角色集合与管理员关联，避免列表 N+1。"""
        if not rows:
            return []
        ids = [row.id for row in rows]
        role_map = self.list_role_ids_for_users(ids)
        return [self._to_entity(row, role_map.get(row.id, ())) for row in rows]

    @staticmethod
    def _to_entity(row: UserModel, role_ids: tuple[UUID, ...] = ()) -> User:
        return User(
            id=row.id,
            tenant_id=row.tenant_id,
            username=row.username,
            password_hash=row.password_hash,
            display_name=row.display_name,
            is_active=row.is_active,
            role_id=row.role_id,
            last_login_at=row.last_login_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            token_version=row.token_version,
            failed_login_count=row.failed_login_count,
            locked_until=row.locked_until,
            must_change_password=row.must_change_password,
            password_changed_at=row.password_changed_at,
            role_ids=role_ids,
        )
