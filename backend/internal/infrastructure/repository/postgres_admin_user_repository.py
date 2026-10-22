"""管理员账号的 PostgreSQL 仓储实现。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.admin_user import AdminUser
from internal.infrastructure.model.admin_user import AdminUserModel


class PostgresAdminUserRepository:
    """基于 SQLAlchemy 的管理员仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_username(self, username: str, tenant_id: int | None) -> AdminUser | None:
        """按用户名与所属租户查询。"""
        row = self._session.scalar(
            select(AdminUserModel).where(
                AdminUserModel.username == username,
                self._tenant_condition(tenant_id),
            )
        )
        return self._to_entity(row) if row else None

    def get_by_username_for_update(self, username: str, tenant_id: int | None) -> AdminUser | None:
        """按用户名与所属租户查询并加行锁。"""
        row = self._session.scalar(
            select(AdminUserModel)
            .where(
                AdminUserModel.username == username,
                self._tenant_condition(tenant_id),
            )
            .with_for_update()
        )
        return self._to_entity(row) if row else None

    def get_by_id(self, user_id: int) -> AdminUser | None:
        """按主键查询。"""
        row = self._session.get(AdminUserModel, user_id)
        return self._to_entity(row) if row else None

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        tenant_id: int | None,
        all_tenants: bool = False,
    ) -> tuple[list[AdminUser], int]:
        """分页查询管理员；all_tenants 为真时跨租户查询。"""
        stmt = select(AdminUserModel)
        if not all_tenants:
            stmt = stmt.where(self._tenant_condition(tenant_id))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AdminUserModel.username.ilike(pattern),
                    AdminUserModel.display_name.ilike(pattern),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(AdminUserModel.created_at.desc(), AdminUserModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def create(self, values: dict[str, Any]) -> AdminUser:
        """创建管理员。"""
        row = AdminUserModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, user_id: int, values: dict[str, Any]) -> AdminUser | None:
        """更新管理员基础字段。"""
        row = self._session.get(AdminUserModel, user_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def mark_login_success(self, user_id: int) -> None:
        """登录成功：清零失败计数并记录最后登录时间。"""
        row = self._session.get(AdminUserModel, user_id)
        if row is None:
            return
        row.failed_login_count = 0
        row.locked_until = None
        row.last_login_at = datetime.now(UTC)
        self._session.flush()

    def record_failed_login(
        self, user_id: int, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，达到阈值后锁定账号。"""
        row = self._session.get(AdminUserModel, user_id, with_for_update=True)
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
        user_id: int,
        password_hash: str,
        must_change_password: bool,
        changed_at: datetime,
    ) -> None:
        """更新密码、递增令牌版本并标记改密时间。"""
        row = self._session.get(AdminUserModel, user_id)
        if row is None:
            return
        row.password_hash = password_hash
        row.must_change_password = must_change_password
        row.password_changed_at = changed_at
        row.token_version += 1
        self._session.flush()

    def bump_token_version(self, user_id: int) -> int:
        """递增令牌版本并返回新版本。"""
        row = self._session.get(AdminUserModel, user_id)
        if row is None:
            return 0
        row.token_version += 1
        self._session.flush()
        return row.token_version

    @staticmethod
    def _tenant_condition(tenant_id: int | None):
        if tenant_id is None:
            return AdminUserModel.tenant_id.is_(None)
        return AdminUserModel.tenant_id == tenant_id

    @staticmethod
    def _to_entity(row: AdminUserModel) -> AdminUser:
        return AdminUser(
            id=row.id,
            username=row.username,
            password_hash=row.password_hash,
            display_name=row.display_name,
            is_active=row.is_active,
            last_login_at=row.last_login_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            role=row.role,
            token_version=row.token_version,
            failed_login_count=row.failed_login_count,
            locked_until=row.locked_until,
            must_change_password=row.must_change_password,
            password_changed_at=row.password_changed_at,
            tenant_id=row.tenant_id,
        )
