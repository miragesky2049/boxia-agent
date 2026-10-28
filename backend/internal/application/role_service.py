"""租户角色管理用例。"""

from __future__ import annotations

import re
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.access import RESOURCE_TYPES, Role
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class RoleService:
    """角色 CRUD；产品级入口创建的角色为系统角色，系统角色不可删除。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(self, tenant_id: UUID | None = None, include_inactive: bool = False) -> list[Role]:
        """查询角色：平台只返回平台角色，租户只返回本租户角色。"""
        target = self._management_scope()
        if self._context.is_platform:
            if tenant_id is not None:
                raise ForbiddenError("产品级平台不能查看租户角色")
        elif tenant_id is not None and tenant_id != target:
            raise ForbiddenError("只能查询本租户角色")
        return self._uow.roles.list_by_tenant(target, include_inactive)

    def get(self, role_id: UUID, tenant_id: UUID | None = None) -> Role:
        """查询角色详情：平台只返回平台角色，租户只返回本租户角色。"""
        target = self._management_scope()
        if self._context.is_platform:
            if tenant_id is not None:
                raise ForbiddenError("产品级平台不能查看租户角色")
        elif tenant_id is not None and tenant_id != target:
            raise ForbiddenError("只能查询本租户角色")
        return self._get_owned(role_id, target)

    def create(
        self,
        *,
        code: str,
        name: str,
        description: str,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """创建当前作用域的角色；产品级入口创建的角色标记为系统角色。"""
        tenant_id = self._management_scope()
        normalized_code = code.strip().lower()
        if not _CODE_PATTERN.match(normalized_code):
            raise ValidationError("角色编码需为 2-64 位小写字母、数字、下划线或短横线")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("角色名称不能为空")
        if self._uow.roles.code_exists(tenant_id, normalized_code):
            raise ConflictError("角色编码已存在")
        if self._uow.roles.name_exists(tenant_id, normalized_name):
            raise ConflictError("角色名称已存在")

        is_system = tenant_id == PLATFORM_TENANT_ID
        role = self._uow.roles.create(
            {
                "tenant_id": tenant_id,
                "code": normalized_code,
                "name": normalized_name,
                "description": description.strip(),
                "is_system": is_system,
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
                "is_system": is_system,
            },
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return role

    def copy(
        self,
        role_id: UUID,
        *,
        code: str,
        name: str,
        description: str | None,
        actor_permissions: frozenset[str],
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """复制角色及其功能权限与数据授权关系，生成同作用域的自定义角色。"""
        tenant_id = self._management_scope()
        source = self._get_owned(role_id, tenant_id)
        if source.is_system and source.code == "superadmin":
            raise ValidationError("超级管理员角色默认拥有全部资源，不支持复制")
        source_codes = self._uow.role_permissions.list_codes_for_role(source.id)
        unauthorized = source_codes - actor_permissions
        if unauthorized:
            raise ForbiddenError(
                f"不能复制包含自身不具备权限的角色：{', '.join(sorted(unauthorized))}"
            )

        normalized_code = code.strip().lower()
        if not _CODE_PATTERN.match(normalized_code):
            raise ValidationError("角色编码需为 2-64 位小写字母、数字、下划线或短横线")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("角色名称不能为空")
        if self._uow.roles.code_exists(tenant_id, normalized_code):
            raise ConflictError("角色编码已存在")
        if self._uow.roles.name_exists(tenant_id, normalized_name):
            raise ConflictError("角色名称已存在")

        role = self._uow.roles.create(
            {
                "tenant_id": tenant_id,
                "code": normalized_code,
                "name": normalized_name,
                "description": source.description if description is None else description.strip(),
                # 副本始终是可删除的自定义角色，权限与数据授权由源角色复制而来
                "is_system": False,
                "is_active": True,
            }
        )
        copied_permissions = self._copy_permissions(source, role, actor_id)
        copied_grants = self._copy_grants(source, role, actor_id)
        record_audit(
            self._uow,
            action="role.copied",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            detail={
                "source_role_id": source.id,
                "code": normalized_code,
                "name": normalized_name,
                "copied_permissions": copied_permissions,
                "copied_grants": copied_grants,
            },
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return role

    def _copy_permissions(self, source: Role, target: Role, granted_by: UUID) -> int:
        """复制源角色的功能权限授权。"""
        codes = self._uow.role_permissions.list_codes_for_role(source.id)
        if not codes:
            return 0
        return self._uow.role_permissions.add_for_role(target.id, codes, granted_by)

    def _copy_grants(self, source: Role, target: Role, granted_by: UUID) -> int:
        """按资源类型复制源角色的显式授权；整租户授权对所有角色生效，无需重复复制。"""
        total = 0
        for resource_type in RESOURCE_TYPES:
            if source.is_platform:
                resource_ids = sorted(
                    self._uow.resource_grants.list_platform_granted_resource_ids(
                        source.id, resource_type
                    )
                )
            else:
                resource_ids = sorted(
                    self._uow.resource_grants.list_granted_resource_ids(source.id, resource_type)
                )
            if not resource_ids:
                continue
            if source.is_platform:
                total += self._uow.resource_grants.add_for_platform_role(
                    target.id, resource_type, resource_ids, granted_by
                )
            else:
                total += self._uow.resource_grants.add_for_role(
                    target.id, source.tenant_id, resource_type, resource_ids, granted_by
                )
        return total

    def update(
        self,
        role_id: UUID,
        *,
        name: str | None,
        description: str | None,
        is_active: bool | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """更新角色名称/描述/启停；功能权限通过角色授权接口单独维护。"""
        tenant_id = self._management_scope()
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
        role_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除角色；被账号或资源授权引用时拒绝。"""
        tenant_id = self._management_scope()
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

    def _management_scope(self) -> UUID:
        """管理作用域：平台返回 PLATFORM_TENANT_ID，租户返回本租户 ID。"""
        if self._context.is_platform:
            return PLATFORM_TENANT_ID
        return self._context.tenant_id

    def _get_owned(self, role_id: UUID, tenant_id: UUID | None) -> Role:
        role = self._uow.roles.get_by_id(role_id)
        if role is None or role.tenant_id != tenant_id:
            raise NotFoundError("角色不存在")
        return role
