"""资源授权用例：平台按租户授权、租户按本租户角色授权。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from internal.application.audit import record_audit
from internal.application.errors import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.access import (
    RESOURCE_TYPES,
    GrantSummary,
    ResourceGrant,
)
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

GRANT_STATES = ("granted", "ungranted")
GRANT_MODES = ("merge", "replace", "clear")
MAX_BATCH_RESOURCES = 100


@dataclass(frozen=True)
class ResourceGrantOverview:
    """授权管理列表项：资源基础信息 + 授权汇总。"""

    resource_id: int
    name: str
    description: str
    is_platform: bool
    is_enabled: bool
    updated_at: datetime
    grant_count: int
    tenant_count: int
    role_count: int


class GrantService:
    """资源授权查询、按资源授权与批量授权。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def overview(
        self,
        resource_type: str,
        page: int,
        page_size: int,
        keyword: str | None,
        grant_state: str | None,
    ) -> Page[ResourceGrantOverview]:
        """分页查询当前作用域可授权的资源及授权汇总。"""
        repository = self._resource_repository(resource_type)
        if grant_state not in (None, *GRANT_STATES):
            raise ValidationError("授权状态必须是 granted 或 ungranted")
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        tenant_id = None if self._context.is_platform else self._require_tenant()
        items, total = repository.list_page(
            page,
            page_size,
            keyword,
            None,
            manageable_only=True,
            grant_state=grant_state,
            grant_tenant_id=tenant_id,
        )
        summaries = self._uow.resource_grants.summary_for_resources(
            resource_type, [item.id for item in items], tenant_id
        )
        overview_items = [self._to_overview(item, summaries.get(item.id)) for item in items]
        return Page(
            items=overview_items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_grants(
        self,
        resource_type: str,
        resource_id: int,
        tenant_id: int | None = None,
    ) -> list[ResourceGrant]:
        """查询资源授权；平台可指定租户，租户视角只能查看本租户。"""
        self._require_resource(resource_type, resource_id)
        if self._context.is_platform:
            return self._uow.resource_grants.list_for_resource(
                resource_type, resource_id, tenant_id
            )
        current_tenant = self._require_tenant()
        if tenant_id is not None and tenant_id != current_tenant:
            raise ForbiddenError("只能查看本租户授权")
        return self._uow.resource_grants.list_for_resource(
            resource_type, resource_id, current_tenant
        )

    def replace(
        self,
        resource_type: str,
        resource_id: int,
        grants: list[tuple[int, int | None]],
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> list[ResourceGrant]:
        """整体替换授权：平台可指定任意租户与角色，租户只能维护本租户角色。"""
        resource = self._require_resource(resource_type, resource_id)
        before = self._uow.resource_grants.list_for_resource(resource_type, resource_id)
        before_view = _grant_views(before)

        if self._context.is_platform:
            if resource.tenant_id is not None:
                raise ForbiddenError("租户自有资源由租户管理员授权")
            normalized = self._validate_platform_grants(grants)
            self._uow.resource_grants.replace_for_resource(
                resource_type, resource_id, normalized, actor_id
            )
            if resource_type == "agent":
                # 兼容旧的产品级授权入口：授权中的租户即视为已开通该产品智能体
                self._uow.agent_openings.sync_for_resource(
                    resource_id,
                    {tenant_id for tenant_id, _ in normalized},
                    actor_id,
                )
            tenant_id = None
        else:
            if resource.tenant_id is None:
                raise ForbiddenError("产品级资源仅产品级运营管理平台可授权")
            tenant_id = self._require_tenant()
            if any(role_id is None for _, role_id in grants):
                raise ValidationError("租户授权必须指定角色")
            role_ids = [int(role_id) for _, role_id in grants if role_id is not None]
            self._validate_tenant_roles(tenant_id, role_ids)
            self._uow.resource_grants.replace_for_tenant(
                resource_type, resource_id, tenant_id, role_ids, actor_id
            )

        after = self._uow.resource_grants.list_for_resource(resource_type, resource_id)
        record_audit(
            self._uow,
            action="grant.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type=resource_type,
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail={"before": before_view, "after": _grant_views(after)},
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return after

    def replace_batch(
        self,
        resource_type: str,
        resource_ids: list[int],
        mode: str,
        tenant_id: int | None,
        role_ids: list[int],
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """批量授权：所有模式都只作用于目标租户，返回处理后的资源数。"""
        repository = self._resource_repository(resource_type)
        if mode not in GRANT_MODES:
            raise ValidationError(f"授权模式必须是 {', '.join(GRANT_MODES)} 之一")
        ids = sorted({int(resource_id) for resource_id in resource_ids})
        if not ids:
            raise ValidationError("请至少选择一个资源")
        if len(ids) > MAX_BATCH_RESOURCES:
            raise ValidationError(f"单次最多授权 {MAX_BATCH_RESOURCES} 个资源")
        if repository.ids_owned(ids) != set(ids):
            raise NotFoundError("部分资源不存在或无权管理")

        target_tenant, scope_roles = self._resolve_batch_scope(mode, tenant_id, role_ids)
        audit_tenant_id = None if self._context.is_platform else target_tenant

        # 先按固定顺序加锁，再读取旧授权，避免并发 merge 丢失更新与死锁
        self._uow.resource_grants.lock_resources(resource_type, ids)
        before_by_resource: dict[int, list[ResourceGrant]] = defaultdict(list)
        for grant in self._uow.resource_grants.list_for_resources(
            resource_type, ids, target_tenant
        ):
            before_by_resource[grant.resource_id].append(grant)

        for resource_id in ids:
            before = before_by_resource.get(resource_id, [])
            new_roles = self._merge_roles(mode, scope_roles, before)
            self._uow.resource_grants.replace_for_tenant(
                resource_type, resource_id, target_tenant, new_roles, actor_id
            )
            if resource_type == "agent" and self._context.is_platform:
                # 批量授权同时维护开通关系：清空授权即关闭，其余模式一律保持开通
                if new_roles == []:
                    self._uow.agent_openings.close(resource_id, target_tenant)
                else:
                    self._uow.agent_openings.open(resource_id, target_tenant, actor_id)
            record_audit(
                self._uow,
                action="grant.updated",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type=resource_type,
                resource_id=str(resource_id),
                ip=ip,
                user_agent=user_agent,
                detail={
                    "mode": mode,
                    "tenant_id": target_tenant,
                    "before": _grant_views(before),
                    "after": _after_view(target_tenant, new_roles),
                    "batch": True,
                },
                tenant_id=audit_tenant_id,
            )
        self._uow.commit()
        return len(ids)

    def assign_user_roles(
        self,
        user_ids: list[int],
        role_ids: list[int],
        tenant_id: int | None,
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """批量给用户追加角色；已存在的角色关联自动跳过。"""
        target_tenant = self._resolve_user_role_tenant(tenant_id)
        unique_users = sorted({int(item) for item in user_ids})
        unique_roles = sorted({int(item) for item in role_ids})
        if not unique_users:
            raise ValidationError("请至少选择一个用户")
        if not unique_roles:
            raise ValidationError("请至少选择一个角色")
        if self._uow.users.ids_existing(target_tenant, unique_users) != set(unique_users):
            raise NotFoundError("部分用户不存在或不属于当前租户")
        self._validate_tenant_roles(target_tenant, unique_roles)
        added = self._uow.users.add_roles_for_users(
            unique_users, target_tenant, unique_roles
        )
        record_audit(
            self._uow,
            action="user.roles_granted",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="user",
            resource_id=",".join(str(item) for item in unique_users),
            ip=ip,
            user_agent=user_agent,
            detail={
                "user_ids": unique_users,
                "role_ids": unique_roles,
                "added": added,
            },
            tenant_id=target_tenant,
        )
        self._uow.commit()
        return added

    def _resolve_user_role_tenant(self, tenant_id: int | None) -> int:
        """用户角色批量授权只允许租户作用域；平台需显式指定租户。"""
        if self._context.is_platform:
            if tenant_id is None:
                raise ValidationError("请选择用户所属租户")
            if self._uow.tenants.get_by_id(tenant_id) is None:
                raise ValidationError(f"租户 {tenant_id} 不存在")
            return tenant_id
        current_tenant = self._require_tenant()
        if tenant_id is not None and tenant_id != current_tenant:
            raise ForbiddenError("只能授权本租户用户")
        return current_tenant

    def _resolve_batch_scope(
        self,
        mode: str,
        tenant_id: int | None,
        role_ids: list[int],
    ) -> tuple[int, list[int] | None]:
        """校验并归一化批量授权目标租户与角色；None 表示整个租户。"""
        normalized_roles = sorted({int(role_id) for role_id in role_ids})
        if self._context.is_platform:
            if tenant_id is None:
                raise ValidationError("请选择授权租户")
            if self._uow.tenants.get_by_id(tenant_id) is None:
                raise ValidationError(f"租户 {tenant_id} 不存在")
            if normalized_roles:
                self._validate_tenant_roles(tenant_id, normalized_roles)
            if mode == "clear":
                return tenant_id, []
            return tenant_id, normalized_roles or None

        current_tenant = self._require_tenant()
        if tenant_id is not None and tenant_id != current_tenant:
            raise ForbiddenError("只能授权本租户角色")
        if mode != "clear" and not normalized_roles:
            raise ValidationError("租户授权必须指定角色")
        if normalized_roles:
            self._validate_tenant_roles(current_tenant, normalized_roles)
        return current_tenant, normalized_roles

    @staticmethod
    def _merge_roles(
        mode: str,
        scope_roles: list[int] | None,
        before: list[ResourceGrant],
    ) -> list[int] | None:
        """按模式计算某资源对该租户的新授权；None 表示整个租户。"""
        if mode == "clear":
            return []
        if mode == "replace":
            return scope_roles
        if scope_roles is None or any(grant.role_id is None for grant in before):
            return None
        existing_roles = {grant.role_id for grant in before if grant.role_id is not None}
        return sorted(existing_roles | set(scope_roles))

    def _to_overview(self, resource: Any, summary: GrantSummary | None) -> ResourceGrantOverview:
        grant_count = summary.grant_count if summary else 0
        return ResourceGrantOverview(
            resource_id=resource.id,
            name=resource.name,
            description=resource.description,
            is_platform=resource.tenant_id is None,
            is_enabled=resource.is_enabled,
            updated_at=resource.updated_at,
            grant_count=grant_count,
            tenant_count=summary.tenant_count if summary else 0,
            role_count=summary.role_count if summary else 0,
        )

    def _resource_repository(self, resource_type: str) -> Any:
        """按资源类型返回当前作用域的仓储。"""
        if resource_type not in RESOURCE_TYPES:
            raise ValidationError(f"资源类型必须是 {', '.join(RESOURCE_TYPES)} 之一")
        repositories = {
            "agent": self._uow.agents,
            "skill": self._uow.skills,
            "tool": self._uow.tools,
            "component": self._uow.components,
            "prompt": self._uow.prompts,
        }
        return repositories[resource_type]

    def _require_resource(self, resource_type: str, resource_id: int) -> Any:
        resource = self._resource_repository(resource_type).get(resource_id)
        if resource is None:
            raise NotFoundError("资源不存在或无权访问")
        return resource

    def _validate_platform_grants(
        self, grants: list[tuple[int, int | None]]
    ) -> list[tuple[int, int | None]]:
        """校验租户存在且角色属于该租户，并去重。"""
        normalized: set[tuple[int, int | None]] = set()
        for tenant_id, role_id in grants:
            if self._uow.tenants.get_by_id(tenant_id) is None:
                raise ValidationError(f"租户 {tenant_id} 不存在")
            if role_id is not None:
                role = self._uow.roles.get_by_id(role_id)
                if role is None or role.tenant_id != tenant_id:
                    raise ValidationError(f"角色 {role_id} 不属于租户 {tenant_id}")
            normalized.add((tenant_id, role_id))
        return sorted(normalized, key=lambda item: (item[0], item[1] or 0))

    def _validate_tenant_roles(self, tenant_id: int, role_ids: list[int]) -> None:
        for role_id in sorted(set(role_ids)):
            role = self._uow.roles.get_by_id(role_id)
            if role is None or role.tenant_id != tenant_id:
                raise ValidationError(f"角色 {role_id} 不属于当前租户")
            if not role.is_active:
                raise ValidationError(f"角色 {role_id} 已停用")

    def _require_tenant(self) -> int:
        if self._context.tenant_id is None:
            raise ForbiddenError("缺少租户上下文")
        return self._context.tenant_id


def _grant_views(grants: list[ResourceGrant]) -> list[dict[str, int | None]]:
    return [{"tenant_id": grant.tenant_id, "role_id": grant.role_id} for grant in grants]


def _after_view(tenant_id: int, role_ids: list[int] | None) -> list[dict[str, int | None]]:
    if role_ids is None:
        return [{"tenant_id": tenant_id, "role_id": None}]
    return [{"tenant_id": tenant_id, "role_id": role_id} for role_id in role_ids]
