"""租户最终用户管理用例（租户超级管理员维护）。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.access import User
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.security.password import hash_password, validate_password_strength

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
# 模块级别名：避免类内 list 方法遮蔽内置类型
RoleIdList = list[int]


class UserAdminService:
    """租户内最终用户 CRUD、角色绑定与密码重置。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(self, page: int, page_size: int, keyword: str | None) -> Page[User]:
        """分页查询本租户最终用户。"""
        tenant_id = self._require_tenant()
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.users.list_page(page, page_size, keyword, tenant_id)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role_ids: Sequence[int],
        is_active: bool,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        """创建最终用户并绑定本租户角色。"""
        tenant_id = self._require_tenant()
        normalized = username.strip()
        if not _USERNAME_PATTERN.match(normalized):
            raise ValidationError("用户名需为 3-64 位字母、数字、下划线、点或短横线")
        resolved_role_ids = self._require_roles(role_ids, tenant_id)
        if self._uow.users.username_exists(tenant_id, normalized):
            raise ConflictError("用户名已存在")
        validate_password_strength(password, normalized)

        user = self._uow.users.create(
            {
                "tenant_id": tenant_id,
                "username": normalized,
                "password_hash": hash_password(password),
                "display_name": display_name.strip() or normalized,
                "is_active": is_active,
                "role_id": resolved_role_ids[0],
            }
        )
        self._uow.users.replace_roles(user.id, tenant_id, resolved_role_ids)
        user = self._uow.users.get_by_id(user.id) or user
        record_audit(
            self._uow,
            action="user.created",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="user",
            resource_id=str(user.id),
            ip=ip,
            user_agent=user_agent,
            detail={"username": normalized, "role_ids": resolved_role_ids},
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return user

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None,
        role_ids: Sequence[int] | None,
        is_active: bool | None,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        """更新最终用户；禁用或改角色时撤销全部会话。"""
        tenant_id = self._require_tenant()
        self._get_owned(user_id, tenant_id)

        values: dict = {}
        resolved_role_ids: RoleIdList | None = None
        if display_name is not None:
            values["display_name"] = display_name.strip()
        if role_ids is not None:
            resolved_role_ids = self._require_roles(role_ids, tenant_id)
            values["role_id"] = resolved_role_ids[0]
        if is_active is not None:
            values["is_active"] = is_active

        updated = self._uow.users.update(user_id, values)
        if updated is None:
            raise NotFoundError("最终用户不存在")
        if resolved_role_ids is not None:
            self._uow.users.replace_roles(user_id, tenant_id, resolved_role_ids)
            updated = self._uow.users.get_by_id(user_id) or updated
        if is_active is False or resolved_role_ids is not None:
            self._uow.users.bump_token_version(user_id)
            self._uow.user_refresh_tokens.revoke_all_for_user(user_id)
            updated = self._uow.users.get_by_id(user_id) or updated

        record_audit(
            self._uow,
            action="user.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            detail={key: value for key, value in values.items() if key != "password_hash"},
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        user_id: int,
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除最终用户（刷新令牌随外键级联删除）。"""
        tenant_id = self._require_tenant()
        target = self._get_owned(user_id, tenant_id)
        if target.id == actor_id:
            raise ValidationError("不能删除当前登录账号")
        if not self._uow.users.delete(user_id):
            raise NotFoundError("最终用户不存在")
        record_audit(
            self._uow,
            action="user.deleted",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            detail={"username": target.username},
            tenant_id=tenant_id,
        )
        self._uow.commit()

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
        """重置密码并撤销全部会话。"""
        tenant_id = self._require_tenant()
        target = self._get_owned(user_id, tenant_id)
        validate_password_strength(new_password, target.username)
        self._uow.users.update_password(user_id, hash_password(new_password))
        self._uow.user_refresh_tokens.revoke_all_for_user(user_id)
        record_audit(
            self._uow,
            action="user.password_reset",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="user",
            resource_id=str(user_id),
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def _require_tenant(self) -> int:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("最终用户仅可由租户平台维护")
        return self._context.tenant_id

    def _require_roles(self, role_ids: Sequence[int], tenant_id: int) -> RoleIdList:
        """校验角色均属于本租户且启用，去重后保持请求顺序。"""
        unique_ids = [int(role_id) for role_id in dict.fromkeys(role_ids)]
        if not unique_ids:
            raise ValidationError("请至少选择一个角色")
        for role_id in unique_ids:
            role = self._uow.roles.get_by_id(role_id)
            if role is None or role.tenant_id != tenant_id:
                raise ValidationError("角色不属于当前租户")
            if not role.is_active:
                raise ValidationError("角色已停用")
        return unique_ids

    def _get_owned(self, user_id: int, tenant_id: int) -> User:
        target = self._uow.users.get_by_id(user_id)
        if target is None or target.tenant_id != tenant_id:
            raise NotFoundError("最终用户不存在")
        return target
