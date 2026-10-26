"""租户最终用户管理用例（租户超级管理员维护）。"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

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
RoleIdList = list[UUID]
UserList = list[User]


class UserAdminService:
    """租户内最终用户 CRUD、角色绑定与密码重置。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        department_id: UUID | None = None,
    ) -> Page[User]:
        """分页查询本租户最终用户；department_id 非空时按部门（含下级）筛选。"""
        tenant_id = self._require_tenant()
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

        filter_user_ids: list[UUID] | None = None
        if department_id is not None:
            filter_department = self._uow.departments.get(department_id)
            if filter_department is None or filter_department.tenant_id != tenant_id:
                raise NotFoundError("筛选部门不存在")
            filter_user_ids = list(
                self._uow.employments.list_current_user_ids_in_subtree(
                    tenant_id, filter_department.path
                )
            )
            if not filter_user_ids:
                return Page(items=[], total=0, page=page, page_size=page_size)

        items, total = self._uow.users.list_page(
            page, page_size, keyword, tenant_id, filter_user_ids
        )
        items = self._attach_departments(tenant_id, items)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role_ids: Sequence[UUID],
        is_active: bool,
        actor_id: UUID,
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
        user_id: UUID,
        *,
        display_name: str | None,
        role_ids: Sequence[UUID] | None,
        is_active: bool | None,
        actor_id: UUID,
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
        user_id: UUID,
        *,
        actor_id: UUID,
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
        user_id: UUID,
        *,
        new_password: str,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """重置密码并撤销全部会话。"""
        tenant_id = self._require_tenant()
        target = self._get_owned(user_id, tenant_id)
        validate_password_strength(new_password, target.username)
        self._uow.users.update_password(
            user_id, hash_password(new_password), False, datetime.now(UTC)
        )
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

    def _require_tenant(self) -> UUID:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("最终用户仅可由租户平台维护")
        return self._context.tenant_id

    def _require_roles(self, role_ids: Sequence[UUID], tenant_id: UUID) -> RoleIdList:
        """校验角色均属于本租户且启用，去重后保持请求顺序。"""
        unique_ids = list(dict.fromkeys(role_ids))
        if not unique_ids:
            raise ValidationError("请至少选择一个角色")
        for role_id in unique_ids:
            role = self._uow.roles.get_by_id(role_id)
            if role is None or role.tenant_id != tenant_id:
                raise ValidationError("角色不属于当前租户")
            if not role.is_active:
                raise ValidationError("角色已停用")
        return unique_ids

    def _get_owned(self, user_id: UUID, tenant_id: UUID) -> User:
        target = self._uow.users.get_by_id(user_id)
        if target is None or target.tenant_id != tenant_id:
            raise NotFoundError("最终用户不存在")
        return target

    def _attach_departments(self, tenant_id: UUID, items: UserList) -> UserList:
        """批量回填用户当前任职部门，避免列表 N+1。"""
        if not items:
            return items
        current_map = self._uow.employments.map_current_for_users(
            tenant_id, [user.id for user in items]
        )
        result: UserList = []
        for user in items:
            current = current_map.get(user.id)
            if current is None:
                result.append(user)
                continue
            department_id, department_name = current
            result.append(
                dataclasses.replace(
                    user,
                    current_department_id=department_id,
                    current_department_name=department_name,
                )
            )
        return result
