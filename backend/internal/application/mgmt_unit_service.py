"""管理单元用例：物化路径树维护、移动子树、停用删除保护、部门/人员关联。"""

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
from internal.domain.entity.mgmt_unit import (
    ManagementUnit,
    MgmtUnitDepartment,
    MgmtUnitUser,
)
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.id.uuid7 import new_uuid

_CODE_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
_MAX_LEVEL = 10


class MgmtUnitService:
    """租户内管理单元 CRUD、移动、停用删除保护与部门/人员关联。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list_tree(self) -> list[ManagementUnit]:
        """按物化路径顺序返回本租户全部管理单元，树结构由 Web 层组装。"""
        tenant_id = self._require_tenant()
        return self._uow.mgmt_units.list_all(tenant_id)

    def list_active_units(self) -> list[ManagementUnit]:
        """返回启用中的管理单元，供授权弹窗勾选。"""
        tenant_id = self._require_tenant()
        return self._uow.mgmt_units.list_active(tenant_id)

    def get(self, unit_id: UUID) -> ManagementUnit:
        """按主键查询管理单元，仅限本租户。"""
        tenant_id = self._require_tenant()
        unit = self._uow.mgmt_units.get(unit_id)
        if unit is None or unit.tenant_id != tenant_id:
            raise NotFoundError("管理单元不存在")
        return unit

    def create(
        self,
        *,
        parent_id: UUID | None,
        name: str,
        code: str | None,
        sort_order: int,
        attrs: dict,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> ManagementUnit:
        """创建管理单元（统一 unit 类型）。"""
        tenant_id = self._require_tenant()
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("管理单元名称不能为空")
        normalized_code = _normalize_code(code)
        parent = self._lock_parent(parent_id, tenant_id)

        if normalized_code and self._uow.mgmt_units.code_exists(tenant_id, normalized_code):
            raise ConflictError("管理单元编码已存在")
        if self._uow.mgmt_units.name_exists_under_parent(
            tenant_id, parent_id, normalized_name
        ):
            raise ConflictError("同一上级下已存在同名管理单元")

        unit_id = new_uuid()
        level = 1 if parent is None else parent.level + 1
        path = _build_path(parent, unit_id)
        unit = self._uow.mgmt_units.create(
            {
                "id": unit_id,
                "tenant_id": tenant_id,
                "parent_id": parent_id,
                "name": normalized_name,
                "code": normalized_code,
                "path": path,
                "level": level,
                "sort_order": sort_order,
                "attrs": dict(attrs or {}),
            }
        )
        self._audit(
            "mgmt_unit.created",
            unit.id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": normalized_name, "parent_id": parent_id},
        )
        self._uow.commit()
        return unit

    def update(
        self,
        unit_id: UUID,
        *,
        parent_id: UUID | None,
        name: str,
        code: str | None,
        sort_order: int,
        attrs: dict,
        is_active: bool,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> ManagementUnit:
        """更新管理单元基础信息；parent_id 变化时执行子树移动。"""
        tenant_id = self._require_tenant()
        unit = self._get_owned(unit_id, tenant_id)
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("管理单元名称不能为空")
        normalized_code = _normalize_code(code)

        if parent_id != unit.parent_id:
            unit = self._move(unit, parent_id)

        if normalized_code and self._uow.mgmt_units.code_exists(
            tenant_id, normalized_code, exclude_id=unit_id
        ):
            raise ConflictError("管理单元编码已存在")
        if self._uow.mgmt_units.name_exists_under_parent(
            tenant_id,
            unit.parent_id,
            normalized_name,
            exclude_id=unit_id,
        ):
            raise ConflictError("同一上级下已存在同名管理单元")

        updated = self._uow.mgmt_units.update(
            unit_id,
            {
                "name": normalized_name,
                "code": normalized_code,
                "sort_order": sort_order,
                "attrs": dict(attrs or {}),
                "is_active": is_active,
            },
        )
        if updated is None:
            raise NotFoundError("管理单元不存在")
        self._audit(
            "mgmt_unit.updated",
            unit_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": normalized_name, "parent_id": unit.parent_id, "is_active": is_active},
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        unit_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """物理删除管理单元；存在子单元或被授权给用户时拒绝。"""
        tenant_id = self._require_tenant()
        unit = self._uow.mgmt_units.get_for_update(unit_id, tenant_id)
        if unit is None:
            raise NotFoundError("管理单元不存在")
        if self._uow.mgmt_units.exists_child(tenant_id, unit_id):
            raise ConflictError("存在子管理单元，不能删除；如不再使用请停用")
        if self._uow.mgmt_units.count_user_grants(tenant_id, unit_id):
            raise ConflictError("该管理单元已授权给用户，不能删除")
        self._uow.mgmt_units.delete(unit_id)
        self._audit(
            "mgmt_unit.deleted",
            unit_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": unit.name},
        )
        self._uow.commit()

    # ------ 部门/人员关联 ------

    def list_departments(self, unit_id: UUID) -> list[MgmtUnitDepartment]:
        """读取管理单元已关联部门。"""
        tenant_id = self._require_tenant()
        self._get_owned(unit_id, tenant_id)
        return self._uow.mgmt_units.list_departments(unit_id)

    def list_users(self, unit_id: UUID) -> list[MgmtUnitUser]:
        """读取管理单元已关联人员。"""
        tenant_id = self._require_tenant()
        self._get_owned(unit_id, tenant_id)
        return self._uow.mgmt_units.list_users(unit_id)

    def replace_departments(
        self,
        unit_id: UUID,
        bindings: list[tuple[UUID, bool]],
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """整体替换管理单元的部门关联；bindings 为 (department_id, include_subtree)。"""
        tenant_id = self._require_tenant()
        unit = self._get_owned(unit_id, tenant_id)
        # 校验部门全部存在于本租户
        department_ids = [dept_id for dept_id, _flag in bindings]
        if department_ids:
            for dept_id in department_ids:
                dept = self._uow.departments.get(dept_id)
                if dept is None or dept.tenant_id != tenant_id:
                    raise ValidationError(f"部门 {dept_id} 不属于当前租户")
        self._uow.mgmt_units.replace_departments(unit_id, bindings)
        self._audit(
            "mgmt_unit.departments_replaced",
            unit_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": unit.name, "department_count": len(bindings)},
        )
        self._uow.commit()

    def replace_users(
        self,
        unit_id: UUID,
        user_ids: list[UUID],
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """整体替换管理单元的人员关联。"""
        tenant_id = self._require_tenant()
        unit = self._get_owned(unit_id, tenant_id)
        if user_ids:
            existing = self._uow.users.ids_existing(tenant_id, user_ids)
            missing = set(user_ids) - existing
            if missing:
                raise ValidationError(f"用户 {sorted(str(x) for x in missing)} 不属于当前租户")
        self._uow.mgmt_units.replace_users(unit_id, user_ids)
        self._audit(
            "mgmt_unit.users_replaced",
            unit_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": unit.name, "user_count": len(user_ids)},
        )
        self._uow.commit()

    # ------ 内部 ------

    def _move(self, unit: ManagementUnit, new_parent_id: UUID | None) -> ManagementUnit:
        """单事务移动子树：统一加锁、防环、层级校验、path/level 平移。"""
        tenant_id = unit.tenant_id
        locked = self._uow.mgmt_units.lock_subtree_and_parent(
            tenant_id, unit.path, new_parent_id
        )
        if not any(item.id == unit.id for item in locked):
            raise NotFoundError("管理单元不存在")
        new_parent = None
        if new_parent_id is not None:
            new_parent = next(
                (item for item in locked if item.id == new_parent_id), None
            )
            if new_parent is None:
                raise NotFoundError("目标上级管理单元不存在")
            if not new_parent.is_active:
                raise ValidationError("目标上级管理单元已停用，不能移入")
            if new_parent.path.startswith(unit.path):
                raise ValidationError("不能将管理单元移动到其自身或下级")

        target_level = 1 if new_parent is None else new_parent.level + 1
        level_delta = target_level - unit.level
        if level_delta > 0:
            subtree_levels = (
                item.level for item in locked if item.path.startswith(unit.path)
            )
            if max(subtree_levels) + level_delta > _MAX_LEVEL:
                raise ValidationError("移动后管理单元层级超过 10 级上限")

        new_path = _build_path(new_parent, unit.id)
        self._uow.mgmt_units.reparent_subtree(
            tenant_id,
            unit.id,
            unit.path,
            new_path,
            new_parent_id,
            level_delta,
        )
        moved = self._uow.mgmt_units.get(unit.id)
        if moved is None:
            raise NotFoundError("管理单元不存在")
        return moved

    def _lock_parent(
        self, parent_id: UUID | None, tenant_id: UUID
    ) -> ManagementUnit | None:
        """创建子单元前锁定父行并校验层级与启用状态。"""
        if parent_id is None:
            return None
        parent = self._uow.mgmt_units.get_for_update(parent_id, tenant_id)
        if parent is None:
            raise NotFoundError("上级管理单元不存在")
        if not parent.is_active:
            raise ValidationError("上级管理单元已停用，不能在其下新建")
        if parent.level >= _MAX_LEVEL:
            raise ValidationError("管理单元层级最多 10 级")
        return parent

    def _get_owned(self, unit_id: UUID, tenant_id: UUID) -> ManagementUnit:
        unit = self._uow.mgmt_units.get(unit_id)
        if unit is None or unit.tenant_id != tenant_id:
            raise NotFoundError("管理单元不存在")
        return unit

    def _require_tenant(self) -> UUID:
        if self._context.is_platform:
            raise ForbiddenError("管理单元仅可由租户平台维护")
        return self._context.tenant_id

    def _audit(
        self,
        action: str,
        resource_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
        tenant_id: UUID,
        detail: dict | None = None,
    ) -> None:
        """写入管理单元操作审计记录。"""
        record_audit(
            self._uow,
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="mgmt_unit",
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail=detail,
            tenant_id=tenant_id,
        )


def _normalize_code(code: str | None) -> str | None:
    """编码去空白并转小写，空串归一为 None；同时校验格式。"""
    if code is None:
        return None
    normalized = code.strip().lower()
    if not normalized:
        return None
    if not _CODE_PATTERN.match(normalized):
        raise ValidationError("编码需为 1-64 位小写字母、数字、下划线或短横线")
    return normalized


def _build_path(parent: ManagementUnit | None, unit_id: UUID) -> str:
    """根单元路径 /<id>/，子单元路径为父路径拼接 <id>/。"""
    if parent is None:
        return f"/{unit_id}/"
    return f"{parent.path}{unit_id}/"
