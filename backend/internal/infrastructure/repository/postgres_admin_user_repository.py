"""管理员账号的 PostgreSQL 仓储实现。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.admin_user import AdminUser
from internal.infrastructure.model.access import RoleModel
from internal.infrastructure.model.admin_user import AdminUserModel


class PostgresAdminUserRepository:
    """基于 SQLAlchemy 的管理员仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_username(self, username: str) -> AdminUser | None:
        """按用户名查询产品级平台账号。"""
        row = self._session.execute(
            _select_with_role().where(AdminUserModel.username == username)
        ).first()
        return self._to_entity(*row) if row else None

    def get_by_username_for_update(self, username: str) -> AdminUser | None:
        """按用户名查询产品级平台账号并加行锁。"""
        row = self._session.execute(
            _select_with_role()
            .where(AdminUserModel.username == username)
            .with_for_update(of=AdminUserModel)
        ).first()
        return self._to_entity(*row) if row else None

    def get_by_id(self, user_id: int) -> AdminUser | None:
        """按主键查询。"""
        row = self._session.execute(
            _select_with_role().where(AdminUserModel.id == user_id)
        ).first()
        return self._to_entity(*row) if row else None

    def delete(self, admin_user_id: int) -> bool:
        """删除管理员账号。"""
        row = self._session.get(AdminUserModel, admin_user_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
    ) -> tuple[list[AdminUser], int]:
        """分页查询产品级平台账号。"""
        criteria: list = []
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            criteria.append(
                or_(
                    AdminUserModel.username.ilike(pattern),
                    AdminUserModel.display_name.ilike(pattern),
                )
            )
        total = self._session.scalar(
            select(func.count())
            .select_from(AdminUserModel)
            .where(*criteria)
        ) or 0
        rows = self._session.execute(
            _select_with_role()
            .where(*criteria)
            .order_by(AdminUserModel.created_at.desc(), AdminUserModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(*row) for row in rows], int(total)

    def create(self, values: dict[str, Any]) -> AdminUser:
        """创建管理员。"""
        row = AdminUserModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        role_code, role_name = self._role_meta(row.role_id)
        return self._to_entity(row, role_code, role_name)

    def update(self, user_id: int, values: dict[str, Any]) -> AdminUser | None:
        """更新管理员基础字段。"""
        row = self._session.get(AdminUserModel, user_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        role_code, role_name = self._role_meta(row.role_id)
        return self._to_entity(row, role_code, role_name)

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

    def _role_meta(self, role_id: int) -> tuple[str, str]:
        role = self._session.get(RoleModel, role_id)
        if role is None:
            return "", ""
        return role.code, role.name

    @staticmethod
    def _to_entity(
        row: AdminUserModel, role_code: str = "", role_name: str = ""
    ) -> AdminUser:
        return AdminUser(
            id=row.id,
            username=row.username,
            password_hash=row.password_hash,
            display_name=row.display_name,
            is_active=row.is_active,
            last_login_at=row.last_login_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            token_version=row.token_version,
            failed_login_count=row.failed_login_count,
            locked_until=row.locked_until,
            must_change_password=row.must_change_password,
            password_changed_at=row.password_changed_at,
            role_id=row.role_id,
            role_code=role_code,
            role_name=role_name,
        )


def _select_with_role():
    """管理员查询统一关联角色，返回 (AdminUserModel, code, name)。"""
    return select(AdminUserModel, RoleModel.code, RoleModel.name).join(
        RoleModel, RoleModel.id == AdminUserModel.role_id
    )
