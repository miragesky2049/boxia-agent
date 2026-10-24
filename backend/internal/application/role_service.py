"""租户角色管理用例。"""

from __future__ import annotations

import re

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.entity.access import Role
from internal.domain.entity.admin_user import ROLES
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class RoleService:
    """租户角色 CRUD；系统角色不可删除、不可变更基础权限。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(self, tenant_id: int | None = None, include_inactive: bool = False) -> list[Role]:
        """查询角色：租户只能查本租户，平台必须显式指定租户。"""
        if self._context.is_platform:
            if tenant_id is None:
                raise ValidationError("产品级平台查询角色必须指定租户")
            target = tenant_id
        else:
            tenant_target = self._context.tenant_id
            if tenant_target is None:
                raise ForbiddenError("缺少租户上下文")
            if tenant_id is not None and tenant_id != tenant_target:
                raise ForbiddenError("只能查询本租户角色")
            target = tenant_target
        return self._uow.roles.list_by_tenant(target, include_inactive)

    def create(
        self,
        *,
        code: str,
        name: str,
        description: str,
        system_role: str,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """创建自定义租户角色。"""
        tenant_id = self._require_tenant_manageable()
        normalized_code = code.strip().lower()
        if not _CODE_PATTERN.match(normalized_code):
            raise ValidationError("角色编码需为 2-64 位小写字母、数字、下划线或短横线")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("角色名称不能为空")
        if system_role not in ROLES:
            raise ValidationError(f"基础权限必须是 {', '.join(ROLES)} 之一")
        if self._uow.roles.code_exists(tenant_id, normalized_code):
            raise ConflictError("角色编码已存在")
        if self._uow.roles.name_exists(tenant_id, normalized_name):
            raise ConflictError("角色名称已存在")

        role = self._uow.roles.create(
            {
                "tenant_id": tenant_id,
                "code": normalized_code,
                "name": normalized_name,
                "description": description.strip(),
                "system_role": system_role,
                "is_system": False,
                "is_active": True,
            }
        )
        record_audit(
            self._uow,
            action="role.created",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            detail={
                "code": normalized_code,
                "name": normalized_name,
                "system_role": system_role,
            },
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return role

    def update(
        self,
        role_id: int,
        *,
        name: str | None,
        description: str | None,
        system_role: str | None,
        is_active: bool | None,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """更新角色；系统角色禁止变更基础权限。"""
        tenant_id = self._require_tenant_manageable()
        role = self._get_owned(role_id, tenant_id)

        values: dict = {}
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValidationError("角色名称不能为空")
            if self._uow.roles.name_exists(tenant_id, normalized_name, exclude_id=role_id):
                raise ConflictError("角色名称已存在")
            values["name"] = normalized_name
        if description is not None:
            values["description"] = description.strip()
        if system_role is not None:
            if role.is_system and system_role != role.system_role:
                raise ValidationError("系统角色的基础权限不可变更")
            if system_role not in ROLES:
                raise ValidationError(f"基础权限必须是 {', '.join(ROLES)} 之一")
            values["system_role"] = system_role
        if is_active is not None:
            if role.is_system and not is_active:
                raise ValidationError("系统角色不可停用")
            values["is_active"] = is_active

        updated = self._uow.roles.update(role_id, values)
        if updated is None:
            raise NotFoundError("角色不存在")
        record_audit(
            self._uow,
            action="role.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="role",
            resource_id=str(role_id),
            ip=ip,
            user_agent=user_agent,
            detail=values,
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        role_id: int,
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除角色；被账号或资源授权引用时拒绝。"""
        tenant_id = self._require_tenant_manageable()
        role = self._get_owned(role_id, tenant_id)
        if role.is_system:
            raise ValidationError("系统角色不可删除")
        if self._uow.roles.count_references(role_id) > 0:
            raise ConflictError("角色仍被账号引用，无法删除")
        if self._uow.resource_grants.count_for_role(role_id) > 0:
            raise ConflictError("角色仍被资源授权引用，无法删除")
        if not self._uow.roles.delete(role_id):
            raise NotFoundError("角色不存在")
        record_audit(
            self._uow,
            action="role.deleted",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="role",
            resource_id=str(role_id),
            ip=ip,
            user_agent=user_agent,
            detail={"code": role.code},
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def _require_tenant_manageable(self) -> int:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("角色仅可由租户超级管理员维护")
        return self._context.tenant_id

    def _get_owned(self, role_id: int, tenant_id: int) -> Role:
        role = self._uow.roles.get_by_id(role_id)
        if role is None or role.tenant_id != tenant_id:
            raise NotFoundError("角色不存在")
        return role
