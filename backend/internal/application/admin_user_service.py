"""管理员账号管理用例：平台账号走 admin_users，租户管理员走 users。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.access import Role, User
from internal.domain.entity.admin_user import AdminUser
from internal.domain.entity.audit_log import AuditLog
from internal.domain.entity.common import MAX_PAGE_SIZE, Page
from internal.domain.entity.permission import CONSOLE_ACCESS, DATA_ALL
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.security.password import hash_password, validate_password_strength

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class AdminUserService:
    """管理员账号 CRUD、角色调整与密码重置。

    产品级平台账号独立存于 admin_users；租户管理员统一存于 users，
    通过角色是否拥有「管理端访问」权限来识别，不再维护基础权限字段。
    """

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(self, page: int, page_size: int, keyword: str | None) -> Page[AdminUser]:
        """分页查询管理员：平台查 admin_users，租户查拥有管理角色的用户。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        if self._context.is_platform:
            items, total = self._uow.admin_users.list_page(page, page_size, keyword)
            return Page(items=items, total=total, page=page, page_size=page_size)
        tenant_id = self._require_tenant()
        rows, total = self._uow.users.list_admin_page(
            tenant_id, page, page_size, keyword, CONSOLE_ACCESS
        )
        role_map = self._role_map(tenant_id)
        console_ids, data_all_ids = self._role_scope_meta(tenant_id)
        items = [
            self._to_admin_user(user, role)
            for user in rows
            for role in [self._pick_admin_role(user, role_map, console_ids, data_all_ids)]
            if role is not None
        ]
        return Page(items=items, total=total, page=page, page_size=page_size)

    def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AdminUser:
        """创建管理员：平台账号首次登录强制改密，租户管理员写 users。"""
        normalized = username.strip()
        if not _USERNAME_PATTERN.match(normalized):
            raise ValidationError("用户名需为 3-64 位字母、数字、下划线、点或短横线")
        if self._context.is_platform:
            return self._create_platform_admin(
                normalized,
                password,
                display_name,
                role_id,
                actor_id,
                actor_username,
                ip,
                user_agent,
            )
        return self._create_tenant_admin(
            normalized,
            password,
            display_name,
            role_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
        )

    def update(
        self,
        user_id: UUID,
        *,
        display_name: str | None,
        role_id: UUID | None,
        is_active: bool | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AdminUser:
        """调整显示名、角色与启用状态；禁用或改角色会撤销全部会话。"""
        if self._context.is_platform:
            return self._update_platform_admin(
                user_id,
                display_name,
                role_id,
                is_active,
                actor_id,
                actor_username,
                ip,
                user_agent,
            )
        return self._update_tenant_admin(
            user_id,
            display_name,
            role_id,
            is_active,
            actor_id,
            actor_username,
            ip,
            user_agent,
        )

    def reset_password(
        self,
        user_id: UUID,
        *,
        new_password: str,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """重置密码并撤销全部会话；平台账号同时要求下次登录改密。"""
        if self._context.is_platform:
            target = self._uow.admin_users.get_by_id(user_id)
            if target is None:
                raise NotFoundError("管理员不存在")
            validate_password_strength(new_password, target.username)
            self._uow.admin_users.update_password(
                user_id, hash_password(new_password), True, datetime.now(UTC)
            )
            self._uow.refresh_tokens.revoke_all_for_user(user_id)
            tenant_id = None
        else:
            tenant_id = self._require_tenant()
            tenant_admin = self._get_tenant_admin(user_id, tenant_id)
            validate_password_strength(new_password, tenant_admin.username)
            self._uow.users.update_password(
                user_id, hash_password(new_password), True, datetime.now(UTC)
            )
            self._uow.user_refresh_tokens.revoke_all_for_user(user_id)
        record_audit(
            self._uow,
            action="admin_user.password_reset",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def delete(
        self,
        user_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除管理员账号；租户管理员即删除对应的用户记录。"""
        if self._context.is_platform:
            target = self._uow.admin_users.get_by_id(user_id)
            if target is None:
                raise NotFoundError("管理员不存在")
            if target.id == actor_id:
                raise ValidationError("不能删除当前登录账号")
            tenant_id = None
            username = target.username
            if not self._uow.admin_users.delete(user_id):
                raise NotFoundError("管理员不存在")
        else:
            tenant_id = self._require_tenant()
            tenant_admin = self._get_tenant_admin(user_id, tenant_id)
            if tenant_admin.id == actor_id:
                raise ValidationError("不能删除当前登录账号")
            username = tenant_admin.username
            if not self._uow.users.delete(user_id):
                raise NotFoundError("管理员不存在")
        record_audit(
            self._uow,
            action="admin_user.deleted",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            detail={"username": username},
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def _create_platform_admin(
        self,
        username: str,
        password: str,
        display_name: str,
        role_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
    ) -> AdminUser:
        """创建产品级平台账号，必须绑定具备管理端访问权限的平台角色。"""
        matched_role = self._resolve_platform_role(role_id)
        self._ensure_console_role(matched_role)
        if self._uow.admin_users.get_by_username(username) is not None:
            raise ConflictError("用户名已存在")
        validate_password_strength(password, username)
        user = self._uow.admin_users.create(
            {
                "username": username,
                "password_hash": hash_password(password),
                "display_name": display_name.strip() or username,
                "role_id": matched_role.id,
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
            detail={
                "role_id": matched_role.id,
                "role_code": matched_role.code,
                "tenant_id": None,
            },
            tenant_id=None,
        )
        self._uow.commit()
        return user

    def _create_tenant_admin(
        self,
        username: str,
        password: str,
        display_name: str,
        role_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
    ) -> AdminUser:
        """在 users 中创建租户管理员，并绑定具备管理端访问权限的角色。"""
        tenant_id = self._require_tenant()
        matched_role = self._resolve_tenant_admin_role(tenant_id, role_id)
        if self._uow.users.username_exists(tenant_id, username):
            raise ConflictError("用户名已存在")
        validate_password_strength(password, username)
        user = self._uow.users.create(
            {
                "tenant_id": tenant_id,
                "username": username,
                "password_hash": hash_password(password),
                "display_name": display_name.strip() or username,
                "is_active": True,
                "role_id": matched_role.id,
                "must_change_password": True,
                "password_changed_at": datetime.now(UTC),
            }
        )
        self._uow.users.replace_roles(user.id, tenant_id, [matched_role.id])
        user = self._uow.users.get_by_id(user.id) or user
        record_audit(
            self._uow,
            action="admin_user.created",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user.id),
            ip=ip,
            user_agent=user_agent,
            detail={
                "role_id": matched_role.id,
                "role_code": matched_role.code,
                "tenant_id": tenant_id,
            },
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return self._to_admin_user(user, matched_role)

    def _update_platform_admin(
        self,
        user_id: UUID,
        display_name: str | None,
        role_id: UUID | None,
        is_active: bool | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
    ) -> AdminUser:
        """调整产品级平台账号；改角色会校验新角色的管理端访问权限。"""
        target = self._uow.admin_users.get_by_id(user_id)
        if target is None:
            raise NotFoundError("管理员不存在")
        values: dict = {}
        if role_id is not None:
            matched_role = self._resolve_platform_role(role_id)
            self._ensure_console_role(matched_role)
            if target.id == actor_id and role_id != target.role_id:
                raise ValidationError("不能修改当前登录账号的角色")
            values["role_id"] = matched_role.id
        if target.id == actor_id and is_active is False:
            raise ValidationError("不能禁用当前登录账号")
        if display_name is not None:
            values["display_name"] = display_name.strip()
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
            detail=values,
            tenant_id=None,
        )
        self._uow.commit()
        return updated

    def _update_tenant_admin(
        self,
        user_id: UUID,
        display_name: str | None,
        role_id: UUID | None,
        is_active: bool | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
    ) -> AdminUser:
        """调整租户管理员；角色变更会整体替换其角色集合。"""
        tenant_id = self._require_tenant()
        target = self._get_tenant_admin(user_id, tenant_id)
        values: dict = {}
        resolved_role: Role | None = None
        if role_id is not None:
            resolved_role = self._resolve_tenant_admin_role(tenant_id, role_id)
            if target.id == actor_id and role_id != target.role_id:
                raise ValidationError("不能修改当前登录账号的角色")
            values["role_id"] = resolved_role.id
        if target.id == actor_id and is_active is False:
            raise ValidationError("不能禁用当前登录账号")
        if display_name is not None:
            values["display_name"] = display_name.strip()
        if is_active is not None:
            values["is_active"] = is_active
        updated = self._uow.users.update(user_id, values)
        if updated is None:
            raise NotFoundError("管理员不存在")
        if resolved_role is not None:
            self._uow.users.replace_roles(user_id, tenant_id, [resolved_role.id])
        if is_active is False or resolved_role is not None:
            self._uow.users.bump_token_version(user_id)
            self._uow.user_refresh_tokens.revoke_all_for_user(user_id)
        updated = self._uow.users.get_by_id(user_id) or updated
        record_audit(
            self._uow,
            action="admin_user.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="admin_user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            detail=values,
            tenant_id=tenant_id,
        )
        self._uow.commit()
        admin_role = resolved_role
        if admin_role is None:
            console_ids, data_all_ids = self._role_scope_meta(tenant_id)
            admin_role = self._pick_admin_role(
                updated, self._role_map(tenant_id), console_ids, data_all_ids
            )
        if admin_role is None:
            raise NotFoundError("管理员不存在")
        return self._to_admin_user(updated, admin_role)

    def _get_tenant_admin(self, user_id: UUID, tenant_id: UUID) -> User:
        """读取本租户且拥有管理端访问权限的用户。"""
        target = self._uow.users.get_by_id(user_id)
        if (
            target is None
            or target.tenant_id != tenant_id
            or not self._uow.users.has_permission(user_id, tenant_id, CONSOLE_ACCESS)
        ):
            raise NotFoundError("管理员不存在")
        return target

    def _role_map(self, tenant_id: UUID) -> dict[UUID, Role]:
        """一次读取租户全部角色，避免逐用户查询。"""
        return {
            role.id: role
            for role in self._uow.roles.list_by_tenant(tenant_id, include_inactive=True)
        }

    def _role_scope_meta(self, tenant_id: UUID) -> tuple[set[UUID], set[UUID]]:
        """返回租户内拥有管理端访问、全量数据权限的角色集合。"""
        return (
            self._uow.role_permissions.list_role_ids_with_code(tenant_id, CONSOLE_ACCESS),
            self._uow.role_permissions.list_role_ids_with_code(tenant_id, DATA_ALL),
        )

    @staticmethod
    def _pick_admin_role(
        user: User,
        role_map: dict[UUID, Role],
        console_role_ids: set[UUID],
        data_all_role_ids: set[UUID],
    ) -> Role | None:
        """从用户角色中选出管理角色，全量数据权限优先。"""
        admin_roles = [
            role
            for role_id in user.effective_role_ids()
            for role in [role_map.get(role_id)]
            if role is not None and role.id in console_role_ids
        ]
        if not admin_roles:
            return None
        for role in admin_roles:
            if role.id in data_all_role_ids:
                return role
        return admin_roles[0]

    def _resolve_tenant_admin_role(self, tenant_id: UUID, role_id: UUID) -> Role:
        """解析租户管理员角色，必须是本租户启用且可访问管理端的角色。"""
        matched = self._uow.roles.get_by_id(role_id)
        if matched is None or matched.tenant_id != tenant_id:
            raise ValidationError("角色不属于当前租户")
        if not matched.is_active:
            raise ValidationError("角色已停用")
        self._ensure_console_role(matched)
        return matched

    def _require_tenant(self) -> UUID:
        tenant_id = self._context.tenant_id
        if self._context.is_platform:
            raise ForbiddenError("租户管理员仅可由租户平台维护")
        return tenant_id

    def _resolve_platform_role(self, role_id: UUID) -> Role:
        """解析平台账号绑定角色，必须是启用的平台角色。"""
        matched = self._uow.roles.get_by_id(role_id)
        if matched is None or matched.tenant_id != PLATFORM_TENANT_ID:
            raise ValidationError("角色不属于产品级平台")
        if not matched.is_active:
            raise ValidationError("角色已停用")
        return matched

    def _ensure_console_role(self, role: Role) -> None:
        """管理员角色必须被授予管理端访问权限，否则无法登录。"""
        if CONSOLE_ACCESS not in self._uow.role_permissions.list_codes_for_role(role.id):
            raise ValidationError("角色未授予管理端访问权限，不能作为管理员角色")

    @staticmethod
    def _to_admin_user(user: User, role: Role) -> AdminUser:
        """把租户用户映射为管理端账号视图。"""
        return AdminUser(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            display_name=user.display_name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
            token_version=user.token_version,
            failed_login_count=user.failed_login_count,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password,
            password_changed_at=user.password_changed_at,
            tenant_id=user.tenant_id,
            role_id=role.id,
            role_code=role.code,
            role_name=role.name,
        )


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
        actor_id: UUID | None,
    ) -> Page[AuditLog]:
        """分页查询审计日志：产品级可看全部，租户只看本租户。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.audit_logs.list_page(
            page, page_size, action, actor_id, self._context.tenant_id
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def clear(self) -> int:
        """清空审计日志：产品级清空全部，租户级只清本租户。返回删除条数。"""
        count = self._uow.audit_logs.delete_all(self._context.tenant_id)
        self._uow.commit()
        return count
