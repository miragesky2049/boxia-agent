"""角色授权明细用例：按资源分类维护角色可见资源。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from internal.application.audit import record_audit
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.access import RESOURCE_TYPES, Role
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

# 模块级别名：避免类内 list 方法遮蔽内置类型
ResourceIdList = list[int]


@dataclass(frozen=True)
class RoleGrantResource:
    """角色授权列表项：资源信息 + 是否已授权。"""

    resource_id: int
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
        role_id: int,
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
        granted_ids = self._uow.resource_grants.list_granted_resource_ids(
            role.id, resource_type
        )
        ids = sorted(granted_ids) if granted_only else None
        items, total = repository.list_grantable(page, page_size, keyword, ids)
        return Page(
            items=[self._to_item(item, item.id in granted_ids) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def replace(
        self,
        role_id: int,
        resource_type: str,
        resource_ids: Sequence[int],
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """整体替换角色在某类资源上的授权。"""
        role = self._require_role(role_id)
        repository = self._resource_repository(resource_type)
        ids = self._validate_ids(repository, resource_ids)
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
        role_id: int,
        resource_type: str,
        resource_ids: Sequence[int],
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """为角色追加授权。"""
        role = self._require_role(role_id)
        repository = self._resource_repository(resource_type)
        ids = self._validate_ids(repository, resource_ids)
        if not ids:
            raise ValidationError("请至少选择一个资源")
        added = self._uow.resource_grants.add_for_role(
            role.id, role.tenant_id, resource_type, ids, actor_id
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
        role_id: int,
        resource_type: str,
        resource_id: int,
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """移除角色对单个资源的授权。"""
        role = self._require_role(role_id)
        self._ensure_resource_type(resource_type)
        if not self._uow.resource_grants.remove_for_role(
            role.id, resource_type, resource_id
        ):
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

    def _require_role(self, role_id: int) -> Role:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("角色授权仅可由租户超级管理员维护")
        role = self._uow.roles.get_by_id(role_id)
        if role is None or role.tenant_id != self._context.tenant_id:
            raise NotFoundError("角色不存在")
        return role

    @staticmethod
    def _ensure_resource_type(resource_type: str) -> None:
        if resource_type not in RESOURCE_TYPES:
            raise ValidationError(
                f"资源类型必须是 {', '.join(RESOURCE_TYPES)} 之一"
            )

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
    def _validate_ids(repository: Any, resource_ids: Sequence[int]) -> ResourceIdList:
        ids = sorted({int(resource_id) for resource_id in resource_ids})
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
            is_platform=resource.tenant_id is None,
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
        actor_id: int,
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
