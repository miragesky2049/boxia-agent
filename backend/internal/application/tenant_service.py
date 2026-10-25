"""租户管理用例（仅产品级运营管理平台可维护）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
from internal.domain.entity.access import SYSTEM_ROLE_SEEDS, AgentTenantOpening
from internal.domain.entity.common import Page
from internal.domain.entity.permission import DEFAULT_ROLE_PERMISSION_CODES
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.resource import Agent
from internal.domain.entity.tenant import Tenant
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.security.password import hash_password, validate_password_strength

_CODE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_CODES = {"www", "api", "admin", "static", "assets", "platform"}


@dataclass(frozen=True)
class TenantAgentView:
    """租户视角的产品智能体及其开通状态。"""

    agent: Agent
    opening: AgentTenantOpening | None

    @property
    def is_opened(self) -> bool:
        """是否已对当前租户开通。"""
        return self.opening is not None


@dataclass(frozen=True)
class AgentTenantView:
    """智能体视角的已开通租户及开通信息。"""

    tenant: Tenant
    opening: AgentTenantOpening


class TenantService:
    """租户 CRUD 与租户初始管理员创建。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list_tenants(self, keyword: str | None = None) -> list[Tenant]:
        """产品级平台查询全部租户。"""
        self._require_platform()
        return self._uow.tenants.search(keyword)

    def list_active(self) -> list[Tenant]:
        """查询启用中的租户（本地调试切换作用域使用）。"""
        return self._uow.tenants.list_active()

    def get(self, tenant_id: UUID) -> Tenant:
        """查询租户详情。"""
        self._require_platform()
        tenant = self._uow.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("租户不存在")
        return tenant

    def create(
        self,
        *,
        code: str,
        name: str,
        admin_username: str,
        admin_password: str,
        admin_display_name: str,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Tenant:
        """创建租户并初始化租户级超级管理员。"""
        self._require_platform()
        normalized_code = code.strip().lower()
        self._validate_code(normalized_code)
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("租户名称不能为空")
        if self._uow.tenants.code_exists(normalized_code):
            raise ConflictError("租户编码已存在")
        if self._uow.tenants.name_exists(normalized_name):
            raise ConflictError("租户名称已存在")
        username = admin_username.strip()
        if self._uow.admin_users.get_by_username(username) is not None:
            raise ConflictError("管理员用户名已被产品级账号占用")
        validate_password_strength(admin_password, username)

        tenant = self._uow.tenants.create(
            {"code": normalized_code, "name": normalized_name, "is_active": True}
        )
        roles = {
            code: self._uow.roles.create(
                {
                    "tenant_id": tenant.id,
                    "code": code,
                    "name": role_name,
                    "description": description,
                    "is_system": True,
                    "is_active": True,
                }
            )
            for code, role_name, description in SYSTEM_ROLE_SEEDS
        }
        # 内置角色按默认权限集合初始化，后续可通过角色授权接口调整
        for code, role in roles.items():
            self._uow.role_permissions.add_for_role(
                role.id,
                DEFAULT_ROLE_PERMISSION_CODES["tenant"][code],
                actor_id,
            )
        if self._uow.users.username_exists(tenant.id, username):
            raise ConflictError("用户名已被租户用户占用")
        admin_user = self._uow.users.create(
            {
                "tenant_id": tenant.id,
                "username": username,
                "password_hash": hash_password(admin_password),
                "display_name": admin_display_name.strip() or username,
                "is_active": True,
                "role_id": roles["superadmin"].id,
                "must_change_password": True,
                "password_changed_at": datetime.now(UTC),
            }
        )
        self._uow.users.replace_roles(admin_user.id, tenant.id, [roles["superadmin"].id])
        record_audit(
            self._uow,
            action="tenant.created",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="tenant",
            resource_id=str(tenant.id),
            ip=ip,
            user_agent=user_agent,
            detail={"code": normalized_code},
            tenant_id=None,
        )
        self._uow.commit()
        return tenant

    def update(
        self,
        tenant_id: UUID,
        *,
        name: str | None,
        is_active: bool | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Tenant:
        """更新租户名称与启用状态。"""
        self._require_platform()
        tenant = self._uow.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("租户不存在")
        values: dict = {}
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValidationError("租户名称不能为空")
            if normalized_name.lower() != tenant.name.lower() and self._uow.tenants.name_exists(
                normalized_name
            ):
                raise ConflictError("租户名称已存在")
            values["name"] = normalized_name
        if is_active is not None:
            values["is_active"] = is_active
        updated = self._uow.tenants.update(tenant_id, values)
        if updated is None:
            raise NotFoundError("租户不存在")
        record_audit(
            self._uow,
            action="tenant.updated",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="tenant",
            resource_id=str(tenant_id),
            ip=ip,
            user_agent=user_agent,
            detail=values,
            tenant_id=None,
        )
        self._uow.commit()
        return updated

    def list_agents(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        opened_only: bool,
    ) -> Page[TenantAgentView]:
        """分页查询产品智能体及该租户的开通状态。"""
        self._require_platform()
        self._require_tenant_exists(tenant_id)
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.agent_openings.list_for_tenant(
            tenant_id, page, page_size, keyword, is_enabled, opened_only
        )
        return Page(
            items=[TenantAgentView(agent=agent, opening=opening) for agent, opening in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def set_agent_opened(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        opened: bool,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AgentTenantOpening | None:
        """开通或关闭产品智能体；关闭时同时清理该租户的角色授权。"""
        self._require_platform()
        self._require_tenant_exists(tenant_id)
        if self._uow.agent_openings.get_platform_agent(agent_id) is None:
            raise NotFoundError("产品智能体不存在")

        if opened:
            opening = self._uow.agent_openings.open(agent_id, tenant_id, actor_id)
        else:
            self._uow.agent_openings.close(agent_id, tenant_id)
            # 关闭后清空角色授权，避免重新开通时把历史授权自动复活
            self._uow.resource_grants.replace_for_tenant("agent", agent_id, tenant_id, [], actor_id)
            opening = None
        record_audit(
            self._uow,
            action="agent.opened" if opened else "agent.closed",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="agent",
            resource_id=str(agent_id),
            ip=ip,
            user_agent=user_agent,
            detail={"tenant_id": tenant_id, "opened": opened},
            tenant_id=None,
        )
        self._uow.commit()
        return opening

    def set_agents_opened(
        self,
        tenant_id: UUID,
        agent_ids: list[UUID],
        opened: bool,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> list[UUID]:
        """批量开通或关闭产品智能体；关闭时同样清理角色授权。"""
        self._require_platform()
        self._require_tenant_exists(tenant_id)
        unique_ids = list(dict.fromkeys(agent_ids))
        existing = self._uow.agent_openings.list_platform_agent_ids(unique_ids)
        missing = [agent_id for agent_id in unique_ids if agent_id not in existing]
        if missing:
            raise NotFoundError(
                f"产品智能体不存在：{', '.join(str(agent_id) for agent_id in missing)}"
            )

        if opened:
            self._uow.agent_openings.open_many(unique_ids, tenant_id, actor_id)
        else:
            self._uow.agent_openings.close_many(unique_ids, tenant_id)
            # 与单个关闭保持一致：先锁资源再清理该租户角色授权，避免并发写入复活历史授权
            self._uow.resource_grants.lock_resources("agent", unique_ids)
            self._uow.resource_grants.delete_for_tenant_resources("agent", unique_ids, tenant_id)

        record_audit(
            self._uow,
            action="agent.batch_opened" if opened else "agent.batch_closed",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="agent",
            ip=ip,
            user_agent=user_agent,
            detail={"tenant_id": tenant_id, "opened": opened, "agent_ids": unique_ids},
            tenant_id=None,
        )
        self._uow.commit()
        return unique_ids

    def list_agent_tenants(
        self,
        agent_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
    ) -> Page[AgentTenantView]:
        """分页查询已开通某产品智能体的租户。"""
        self._require_platform()
        if self._uow.agent_openings.get_platform_agent(agent_id) is None:
            raise NotFoundError("产品智能体不存在")
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.agent_openings.list_opened_tenants(
            agent_id, page, page_size, keyword
        )
        return Page(
            items=[AgentTenantView(tenant=tenant, opening=opening) for tenant, opening in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def _require_tenant_exists(self, tenant_id: UUID) -> Tenant:
        tenant = self._uow.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("租户不存在")
        return tenant

    def _require_platform(self) -> None:
        if not self._context.is_platform:
            raise ForbiddenError("该操作仅产品级运营管理平台可用")

    @staticmethod
    def _validate_code(code: str) -> None:
        settings = get_settings()
        reserved = set(_RESERVED_CODES)
        reserved.add(settings.platform_admin_subdomain.strip().lower())
        if not _CODE_PATTERN.match(code):
            raise ValidationError(
                "租户编码需为 1-63 位小写字母、数字或短横线，且不能以短横线开头结尾"
            )
        if code in reserved:
            raise ValidationError(f"租户编码 {code} 为系统保留字")
