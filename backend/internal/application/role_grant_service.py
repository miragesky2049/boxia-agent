"""角色授权明细用例：按资源分类维护角色可见资源。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.access import RESOURCE_TYPES, Role
from internal.domain.entity.common import Page
from internal.domain.entity.permission import DATA_ALL
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

# 模块级别名：避免类内 list 方法遮蔽内置类型
ResourceIdList = list[UUID]


@dataclass(frozen=True)
class RoleGrantResource:
    """角色授权列表项：资源信息 + 是否已授权。"""

    resource_id: UUID
    name: str
    description: str
    is_platform: bool
    is_enabled: bool
    updated_at: datetime
    is_granted: bool


class RoleGrantService:
    """角色详情内的授权明细增删改查。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        role_id: UUID,
        resource_type: str,
        page: int,
        page_size: int,
        keyword: str | None,
        granted_only: bool = True,
    ) -> Page[RoleGrantResource]:
        """按资源分类查询授权候选；granted_only 为真时只返回已授权资源。"""
        role = self._require_role(role_id)
        repository = self._resource_repository(resource_type)
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        if self._has_all_resources(role):
            # 全量数据权限角色默认拥有作用域内全部资源，授权页只读展示全量
            items, total = repository.list_grantable(page, page_size, keyword, None)
            return Page(
                items=[self._to_item(item, True) for item in items],
                total=total,
                page=page,
                page_size=page_size,
            )
        granted_ids = self._granted_ids(role, resource_type)
        ids = sorted(granted_ids) if granted_only else None
        items, total = repository.list_grantable(page, page_size, keyword, ids)
        return Page(
            items=[self._to_item(item, item.id in granted_ids) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def summary(self, role_id: UUID) -> dict[str, int]:
        """按资源类型统计角色的有效授权数量。"""
        role = self._require_role(role_id)
        implicit_full = self._has_all_resources(role)
        return {
            resource_type: self._granted_count(role, resource_type, implicit_full=implicit_full)
            for resource_type in RESOURCE_TYPES
        }

    def replace(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: Sequence[UUID],
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """整体替换角色在某类资源上的授权。"""
        role = self._require_writable_role(role_id)
        repository = self._resource_repository(resource_type)
        ids = self._validate_ids(repository, resource_ids)
        # 与平台侧按资源写入串行化，避免同一资源的并发替换相互覆盖
        self._uow.resource_grants.lock_resources(resource_type, ids)
        if role.is_platform:
            self._uow.resource_grants.replace_for_platform_role(
                role.id, resource_type, ids, actor_id
            )
        else:
            self._uow.resource_grants.replace_for_role(
                role.id, role.tenant_id, resource_type, ids, actor_id
            )
        self._record_audit(
            role,
            resource_type,
            action="role.grant.updated",
            detail={"resource_ids": ids},
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()
        return len(ids)

    def add(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: Sequence[UUID],
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """为角色追加授权；已整租户授权的资源无需重复写入。"""
        role = self._require_writable_role(role_id)
        repository = self._resource_repository(resource_type)
        ids = self._validate_ids(repository, resource_ids)
        if not ids:
            raise ValidationError("请至少选择一个资源")
        self._uow.resource_grants.lock_resources(resource_type, ids)
        if role.is_platform:
            added = self._uow.resource_grants.add_for_platform_role(
                role.id, resource_type, ids, actor_id
            )
        else:
            tenant_wide = self._uow.resource_grants.list_tenant_wide_resource_ids(
                role.tenant_id, resource_type
            )
            pending = [resource_id for resource_id in ids if resource_id not in tenant_wide]
            if not pending:
                return 0
            added = self._uow.resource_grants.add_for_role(
                role.id, role.tenant_id, resource_type, pending, actor_id
            )
        self._record_audit(
            role,
            resource_type,
            action="role.grant.added",
            detail={"resource_ids": ids, "added": added},
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()
        return added

    def remove(
        self,
        role_id: UUID,
        resource_type: str,
        resource_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """移除角色对单个资源的授权；整租户授权会拆成其余角色的显式授权。"""
        role = self._require_writable_role(role_id)
        self._ensure_resource_type(resource_type)
        # 先锁资源再判断整租户授权，避免并发取消时把已移除的角色重新写回
        self._uow.resource_grants.lock_resources(resource_type, [resource_id])
        if role.is_platform:
            if not self._uow.resource_grants.remove_for_platform_role(
                role.id, resource_type, resource_id
            ):
                raise NotFoundError("授权不存在")
        elif self._uow.resource_grants.has_tenant_wide(resource_type, resource_id, role.tenant_id):
            self._demote_tenant_wide(role, resource_type, resource_id, actor_id)
        elif not self._uow.resource_grants.remove_for_role(role.id, resource_type, resource_id):
            raise NotFoundError("授权不存在")
        self._record_audit(
            role,
            resource_type,
            action="role.grant.removed",
            detail={"resource_id": resource_id},
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()

    def _scope(self) -> UUID:
        """管理作用域：平台返回 PLATFORM_TENANT_ID，租户返回本租户 ID。"""
        if self._context.is_platform:
            return PLATFORM_TENANT_ID
        return self._context.tenant_id

    def _require_role(self, role_id: UUID) -> Role:
        role = self._uow.roles.get_by_id(role_id)
        if role is None or role.tenant_id != self._scope():
            raise NotFoundError("角色不存在")
        return role

    def _require_writable_role(self, role_id: UUID) -> Role:
        role = self._require_role(role_id)
        if self._has_all_resources(role):
            raise ValidationError("超级管理员角色默认拥有全部资源，不可单独授权")
        return role

    def _granted_ids(self, role: Role, resource_type: str) -> set[UUID]:
        """角色已授权资源 ID：平台角色看平台授权，租户角色合并整租户授权。"""
        if role.is_platform:
            return self._uow.resource_grants.list_platform_granted_resource_ids(
                role.id, resource_type
            )
        return self._uow.resource_grants.list_effective_granted_resource_ids(
            role.id, role.tenant_id, resource_type
        )

    def _granted_count(self, role: Role, resource_type: str, *, implicit_full: bool = False) -> int:
        """角色已授权资源数量；全量数据权限角色按作用域全量统计。"""
        if implicit_full:
            repository = self._resource_repository(resource_type)
            return repository.list_grantable(1, 1, None, None)[1]
        if role.is_platform:
            return self._uow.resource_grants.count_platform_granted(role.id, resource_type)
        return self._uow.resource_grants.count_effective_granted(
            role.id, role.tenant_id, resource_type
        )

    def _has_all_resources(self, role: Role) -> bool:
        """拥有全量数据权限的角色默认可见作用域内全部资源，无需显式授权。"""
        return DATA_ALL in self._uow.role_permissions.list_codes_for_role(role.id)

    def _demote_tenant_wide(
        self, role: Role, resource_type: str, resource_id: UUID, actor_id: UUID
    ) -> None:
        """把整租户授权拆成除目标角色外其余角色的显式授权。"""
        tenant_id = role.tenant_id
        if role.is_platform:
            raise ValidationError("平台角色不支持整租户授权")
        remaining = [
            item.id
            for item in self._uow.roles.list_by_tenant(tenant_id, include_inactive=True)
            if item.id != role.id
        ]
        self._uow.resource_grants.replace_for_tenant(
            resource_type, resource_id, tenant_id, remaining, actor_id
        )

    @staticmethod
    def _ensure_resource_type(resource_type: str) -> None:
        if resource_type not in RESOURCE_TYPES:
            raise ValidationError(f"资源类型必须是 {', '.join(RESOURCE_TYPES)} 之一")

    def _resource_repository(self, resource_type: str) -> Any:
        self._ensure_resource_type(resource_type)
        repositories = {
            "agent": self._uow.agents,
            "skill": self._uow.skills,
            "tool": self._uow.tools,
            "component": self._uow.components,
            "prompt": self._uow.prompts,
        }
        return repositories[resource_type]

    @staticmethod
    def _validate_ids(repository: Any, resource_ids: Sequence[UUID]) -> ResourceIdList:
        ids = sorted(set(resource_ids))
        if not ids:
            return []
        if repository.ids_grantable(ids) != set(ids):
            raise NotFoundError("部分资源不存在或无权授权")
        return ids

    @staticmethod
    def _to_item(resource: Any, is_granted: bool) -> RoleGrantResource:
        return RoleGrantResource(
            resource_id=resource.id,
            name=resource.name,
            description=resource.description,
            is_platform=resource.tenant_id == PLATFORM_TENANT_ID,
            is_enabled=resource.is_enabled,
            updated_at=resource.updated_at,
            is_granted=is_granted,
        )

    def _record_audit(
        self,
        role: Role,
        resource_type: str,
        *,
        action: str,
        detail: dict,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        record_audit(
            self._uow,
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type=resource_type,
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            detail={"role_id": role.id, **detail},
            tenant_id=role.tenant_id,
        )
