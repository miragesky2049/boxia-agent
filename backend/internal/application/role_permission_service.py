"""角色功能权限用例：权限目录查询与角色-权限资源授权维护。"""

from __future__ import annotations

from collections.abc import Iterable

from internal.application.audit import record_audit
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.entity.access import Role
from internal.domain.entity.permission import (
    PLATFORM_ONLY_CODES,
    TENANT_ONLY_CODES,
    PermissionResource,
)
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork


class RolePermissionService:
    """角色功能权限目录与授权；平台与租户各自只能维护本作用域角色。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def catalog(self) -> list[PermissionResource]:
        """查询当前作用域可授权的功能权限目录。"""
        resources = self._uow.permission_resources.list_all()
        if self._context.is_platform:
            return [item for item in resources if item.code not in TENANT_ONLY_CODES]
        return [item for item in resources if item.code not in PLATFORM_ONLY_CODES]

    def list_for_role(self, role_id: int) -> list[PermissionResource]:
        """查询角色已授予的功能权限。"""
        role = self._require_role(role_id)
        granted = self._uow.role_permissions.list_codes_for_role(role.id)
        return [item for item in self.catalog() if item.code in granted]

    def replace(
        self,
        role_id: int,
        codes: Iterable[str],
        *,
        actor_permissions: frozenset[str],
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> list[PermissionResource]:
        """整体替换角色权限；仅允许授予调用者自身拥有的权限。"""
        role = self._require_writable_role(role_id)
        normalized = self._normalize_codes(codes)
        current = self._uow.role_permissions.list_codes_for_role(role.id)
        self._ensure_no_escalation(normalized - current, actor_permissions)
        # 锁定角色行，串行化同一角色的并发授权写入
        if not self._uow.role_permissions.lock_role(role.id):
            raise NotFoundError("角色不存在")
        role = self._require_writable_role(role_id)
        self._uow.role_permissions.replace_for_role(role.id, normalized, actor_id)
        self._record_audit(
            role,
            action="role.permissions.replaced",
            detail={
                "permission_codes": sorted(normalized),
                "added": sorted(normalized - current),
                "removed": sorted(current - normalized),
            },
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()
        return self.list_for_role(role.id)

    def add(
        self,
        role_id: int,
        codes: Iterable[str],
        *,
        actor_permissions: frozenset[str],
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> list[PermissionResource]:
        """追加角色权限；仅允许授予调用者自身拥有的权限。"""
        role = self._require_writable_role(role_id)
        normalized = self._normalize_codes(codes)
        if not normalized:
            raise ValidationError("请至少选择一个权限")
        current = self._uow.role_permissions.list_codes_for_role(role.id)
        self._ensure_no_escalation(normalized - current, actor_permissions)
        if not self._uow.role_permissions.lock_role(role.id):
            raise NotFoundError("角色不存在")
        role = self._require_writable_role(role_id)
        added = self._uow.role_permissions.add_for_role(role.id, normalized, actor_id)
        self._record_audit(
            role,
            action="role.permissions.granted",
            detail={"permission_codes": sorted(normalized), "added": added},
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()
        return self.list_for_role(role.id)

    def remove(
        self,
        role_id: int,
        code: str,
        *,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """移除角色对单个功能权限的授权。"""
        role = self._require_writable_role(role_id)
        normalized = code.strip()
        if not normalized:
            raise ValidationError("权限编码不能为空")
        if not self._uow.role_permissions.lock_role(role.id):
            raise NotFoundError("角色不存在")
        role = self._require_writable_role(role_id)
        if not self._uow.role_permissions.remove_for_role(role.id, normalized):
            raise NotFoundError("该角色未授予此权限")
        self._record_audit(
            role,
            action="role.permissions.revoked",
            detail={"permission_code": normalized},
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )
        self._uow.commit()

    def _normalize_codes(self, codes: Iterable[str]) -> set[str]:
        """去重并校验编码存在、属于当前作用域。"""
        normalized = {code.strip() for code in codes if code and code.strip()}
        if not normalized:
            return set()
        existing = self._uow.permission_resources.existing_codes(normalized)
        unknown = normalized - existing
        if unknown:
            raise ValidationError(f"权限编码不存在或已停用：{', '.join(sorted(unknown))}")
        if self._context.is_platform:
            forbidden = normalized & TENANT_ONLY_CODES
            if forbidden:
                raise ValidationError(
                    f"平台角色不能授予租户级权限：{', '.join(sorted(forbidden))}"
                )
        else:
            forbidden = normalized & PLATFORM_ONLY_CODES
            if forbidden:
                raise ValidationError(
                    f"租户角色不能授予平台级权限：{', '.join(sorted(forbidden))}"
                )
        return normalized

    @staticmethod
    def _ensure_no_escalation(
        added: set[str], actor_permissions: frozenset[str]
    ) -> None:
        """禁止授予调用者自身不具备的权限，防止横向提权。"""
        unauthorized = added - actor_permissions
        if unauthorized:
            raise ForbiddenError(
                f"不能授予自身不具备的权限：{', '.join(sorted(unauthorized))}"
            )

    def _scope(self) -> int | None:
        """管理作用域：平台返回 None（平台角色），租户返回本租户 ID。"""
        if self._context.is_platform:
            return None
        if self._context.tenant_id is None:
            raise ForbiddenError("缺少租户上下文")
        return self._context.tenant_id

    def _require_role(self, role_id: int) -> Role:
        role = self._uow.roles.get_by_id(role_id)
        if role is None or role.tenant_id != self._scope():
            raise NotFoundError("角色不存在")
        return role

    def _require_writable_role(self, role_id: int) -> Role:
        """超级管理员角色默认拥有全部权限，不允许单独调整。"""
        role = self._require_role(role_id)
        if role.is_system and role.code == "superadmin":
            raise ValidationError("超级管理员角色默认拥有全部权限，不可单独授权")
        return role

    def _record_audit(
        self,
        role: Role,
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
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            detail={"role_id": role.id, **detail},
            tenant_id=role.tenant_id,
        )
