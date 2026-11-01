"""租户管理用例（仅产品级运营管理平台可维护）。"""

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
from internal.domain.entity.access import SYSTEM_ROLE_SEEDS
from internal.domain.entity.hr_dictionary_seed import DEFAULT_HR_DICTIONARY_ITEMS
from internal.domain.entity.permission import DEFAULT_ROLE_PERMISSION_CODES
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.tenant import Tenant
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.security.password import hash_password, validate_password_strength

_CODE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_CODES = {"www", "api", "admin", "static", "assets", "platform"}


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
        for category, code, name, sort_order in DEFAULT_HR_DICTIONARY_ITEMS:
            self._uow.hr_dictionaries.create(
                {
                    "id": new_uuid(),
                    "tenant_id": tenant.id,
                    "category": category,
                    "code": code,
                    "name": name,
                    "sort_order": sort_order,
                    "is_active": True,
                    "remark": "",
                }
            )
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
