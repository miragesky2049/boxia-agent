"""管理员账号管理用例（仅 superadmin 可调用）。"""

import re
from datetime import UTC, datetime

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.admin_user import ROLES, AdminUser
from internal.domain.entity.audit_log import AuditLog
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.security.password import hash_password, validate_password_strength

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class AdminUserService:
    """管理员账号 CRUD、角色调整与密码重置（按作用域隔离）。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        tenant_id: int | None = None,
    ) -> Page[AdminUser]:
        """分页查询管理员：租户只查本租户，产品级默认查平台账号。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        scope_tenant_id = tenant_id if self._context.is_platform else self._context.tenant_id
        items, total = self._uow.admin_users.list_page(page, page_size, keyword, scope_tenant_id)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def list_all_tenants(self, page: int, page_size: int, keyword: str | None) -> Page[AdminUser]:
        """产品级平台跨租户查询全部账号。"""
        self._require_platform()
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.admin_users.list_page(
            page, page_size, keyword, None, all_tenants=True
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str,
        actor_id: int,
        actor_username: str,
        tenant_id: int | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AdminUser:
        """创建管理员，首次登录强制改密；租户账号归属当前租户。"""
        normalized = username.strip()
        if not _USERNAME_PATTERN.match(normalized):
            raise ValidationError("用户名需为 3-64 位字母、数字、下划线、点或短横线")
        self._validate_role(role)
        target_tenant_id = self._resolve_target_tenant(tenant_id)
        if target_tenant_id is not None and self._uow.tenants.get_by_id(target_tenant_id) is None:
            raise NotFoundError("租户不存在")
        if self._uow.admin_users.get_by_username(normalized, target_tenant_id) is not None:
            raise ConflictError("用户名已存在")
        validate_password_strength(password, normalized)

        user = self._uow.admin_users.create(
            {
                "tenant_id": target_tenant_id,
                "username": normalized,
                "password_hash": hash_password(password),
                "display_name": display_name.strip(),
                "role": role,
                "is_active": True,
                "must_change_password": True,
                "password_changed_at": datetime.now(UTC),
            }
        )
        record_audit(
            self._uow,
            action="admin_user.created",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user.id),
            ip=ip,
            user_agent=user_agent,
            detail={"role": role, "tenant_id": target_tenant_id},
            tenant_id=target_tenant_id,
        )
        self._uow.commit()
        return user

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None,
        role: str | None,
        is_active: bool | None,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AdminUser:
        """调整显示名、角色与启用状态；禁用会撤销全部会话。"""
        target = self._uow.admin_users.get_by_id(user_id)
        if target is None:
            raise NotFoundError("管理员不存在")
        self._ensure_manageable(target)
        if target.id == actor_id:
            if is_active is False:
                raise ValidationError("不能禁用当前登录账号")
            if role is not None and role != "superadmin":
                raise ValidationError("不能降低当前登录账号的角色")

        values: dict = {}
        if display_name is not None:
            values["display_name"] = display_name.strip()
        if role is not None:
            self._validate_role(role)
            values["role"] = role
        if is_active is not None:
            values["is_active"] = is_active

        updated = self._uow.admin_users.update(user_id, values)
        if updated is None:
            raise NotFoundError("管理员不存在")
        if is_active is False:
            self._uow.admin_users.bump_token_version(user_id)
            self._uow.refresh_tokens.revoke_all_for_user(user_id)

        record_audit(
            self._uow,
            action="admin_user.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            detail={key: value for key, value in values.items() if key != "password_hash"},
            tenant_id=target.tenant_id,
        )
        self._uow.commit()
        return updated

    def reset_password(
        self,
        user_id: int,
        *,
        new_password: str,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """重置密码，强制下次登录改密并撤销全部会话。"""
        target = self._uow.admin_users.get_by_id(user_id)
        if target is None:
            raise NotFoundError("管理员不存在")
        self._ensure_manageable(target)
        validate_password_strength(new_password, target.username)
        self._uow.admin_users.update_password(
            user_id, hash_password(new_password), True, datetime.now(UTC)
        )
        self._uow.refresh_tokens.revoke_all_for_user(user_id)
        record_audit(
            self._uow,
            action="admin_user.password_reset",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            tenant_id=target.tenant_id,
        )
        self._uow.commit()

    def _resolve_target_tenant(self, tenant_id: int | None) -> int | None:
        """计算新账号归属：租户上下文强制本租户，产品级可指定租户或平台。"""
        if not self._context.is_platform:
            if tenant_id is not None and tenant_id != self._context.tenant_id:
                raise ForbiddenError("租户级平台只能维护本租户账号")
            return self._context.tenant_id
        return tenant_id

    def _ensure_manageable(self, target: AdminUser) -> None:
        """租户级平台只能维护本租户账号。"""
        if not self._context.is_platform and target.tenant_id != self._context.tenant_id:
            raise ForbiddenError("租户级平台只能维护本租户账号")

    def _require_platform(self) -> None:
        if not self._context.is_platform:
            raise ForbiddenError("该操作仅产品级运营管理平台可用")

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ROLES:
            raise ValidationError(f"角色必须是 {', '.join(ROLES)} 之一")


class AuditService:
    """审计日志查询（按作用域隔离）。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        action: str | None,
        actor_id: int | None,
    ) -> Page[AuditLog]:
        """分页查询审计日志：产品级可看全部，租户只看本租户。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.audit_logs.list_page(
            page, page_size, action, actor_id, self._context.tenant_id
        )
        return Page(items=items, total=total, page=page, page_size=page_size)
