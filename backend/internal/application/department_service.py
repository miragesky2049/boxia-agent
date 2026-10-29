"""部门管理用例：物化路径树维护、移动子树、停用删除保护。"""

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
from internal.domain.entity.department import Department
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.id.uuid7 import new_uuid

_CODE_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
_MAX_LEVEL = 10


class DepartmentService:
    """租户内部门 CRUD、移动、停用与删除保护。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list_tree(self) -> list[Department]:
        """按物化路径顺序返回本租户全部部门，树结构由 Web 层组装。"""
        tenant_id = self._require_tenant()
        return self._uow.departments.list_all(tenant_id)

    def create(
        self,
        *,
        parent_id: UUID | None,
        name: str,
        code: str | None,
        sort_order: int,
        is_active: bool,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Department:
        """创建部门，根部门 parent_id 为空。"""
        tenant_id = self._require_tenant()
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("部门名称不能为空")
        normalized_code = _normalize_code(code)
        parent = self._lock_parent(parent_id, tenant_id)

        if normalized_code and self._uow.departments.code_exists(
            tenant_id, normalized_code
        ):
            raise ConflictError("部门编码已存在")
        if self._uow.departments.name_exists_under_parent(
            tenant_id, parent_id, normalized_name
        ):
            raise ConflictError("同一上级下已存在同名部门")

        department_id = new_uuid()
        level = 1 if parent is None else parent.level + 1
        path = _build_path(parent, department_id)
        department = self._uow.departments.create(
            {
                "id": department_id,
                "tenant_id": tenant_id,
                "parent_id": parent_id,
                "name": normalized_name,
                "code": normalized_code,
                "path": path,
                "level": level,
                "sort_order": sort_order,
                "is_active": is_active,
            }
        )
        self._audit(
            "department.created",
            department.id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": normalized_name, "parent_id": parent_id},
        )
        self._uow.commit()
        return department

    def update(
        self,
        department_id: UUID,
        *,
        parent_id: UUID | None,
        name: str,
        code: str | None,
        sort_order: int,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Department:
        """更新部门基础信息；parent_id 变化时执行子树移动。"""
        tenant_id = self._require_tenant()
        department = self._get_owned(department_id, tenant_id)
        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationError("部门名称不能为空")
        normalized_code = _normalize_code(code)

        if parent_id != department.parent_id:
            department = self._move(department, parent_id)

        if normalized_code and self._uow.departments.code_exists(
            tenant_id, normalized_code, exclude_id=department_id
        ):
            raise ConflictError("部门编码已存在")
        if self._uow.departments.name_exists_under_parent(
            tenant_id,
            department.parent_id,
            normalized_name,
            exclude_id=department_id,
        ):
            raise ConflictError("同一上级下已存在同名部门")

        updated = self._uow.departments.update(
            department_id,
            {
                "name": normalized_name,
                "code": normalized_code,
                "sort_order": sort_order,
            },
        )
        if updated is None:
            raise NotFoundError("部门不存在")
        self._audit(
            "department.updated",
            department_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": normalized_name, "parent_id": department.parent_id},
        )
        self._uow.commit()
        return updated

    def set_active(
        self,
        department_id: UUID,
        *,
        is_active: bool,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Department:
        """停用或启用部门。"""
        tenant_id = self._require_tenant()
        self._get_owned(department_id, tenant_id)
        updated = self._uow.departments.update(department_id, {"is_active": is_active})
        if updated is None:
            raise NotFoundError("部门不存在")
        self._audit(
            "department.activated" if is_active else "department.disabled",
            department_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        department_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """物理删除部门；存在子部门/任职/归属智能体时拒绝。"""
        tenant_id = self._require_tenant()
        department = self._uow.departments.get_for_update(department_id, tenant_id)
        if department is None:
            raise NotFoundError("部门不存在")
        if self._uow.departments.exists_child(tenant_id, department_id):
            raise ConflictError("存在子部门，不能删除；如不再使用请停用部门")
        if self._uow.departments.count_employments(tenant_id, department_id):
            raise ConflictError("部门下存在任职记录，不能删除；如不再使用请停用部门")
        self._uow.departments.delete(department_id)
        self._audit(
            "department.deleted",
            department_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"name": department.name},
        )
        self._uow.commit()

    def _move(self, department: Department, new_parent_id: UUID | None) -> Department:
        """单事务移动子树：统一加锁、防环、层级校验、path/level 平移。"""
        tenant_id = department.tenant_id
        locked = self._uow.departments.lock_subtree_and_parent(
            tenant_id, department.path, new_parent_id
        )
        if not any(item.id == department.id for item in locked):
            raise NotFoundError("部门不存在")
        new_parent = None
        if new_parent_id is not None:
            new_parent = next(
                (item for item in locked if item.id == new_parent_id), None
            )
            if new_parent is None:
                raise NotFoundError("目标上级部门不存在")
            if not new_parent.is_active:
                raise ValidationError("目标上级部门已停用，不能移入")
            if new_parent.path.startswith(department.path):
                raise ValidationError("不能将部门移动到其自身或下级部门")

        target_level = 1 if new_parent is None else new_parent.level + 1
        level_delta = target_level - department.level
        if level_delta > 0:
            subtree_levels = (
                item.level for item in locked if item.path.startswith(department.path)
            )
            if max(subtree_levels) + level_delta > _MAX_LEVEL:
                raise ValidationError("移动后部门层级超过 10 级上限")

        new_path = _build_path(new_parent, department.id)
        self._uow.departments.reparent_subtree(
            tenant_id,
            department.id,
            department.path,
            new_path,
            new_parent_id,
            level_delta,
        )
        moved = self._uow.departments.get(department.id)
        if moved is None:
            raise NotFoundError("部门不存在")
        return moved

    def _lock_parent(self, parent_id: UUID | None, tenant_id: UUID) -> Department | None:
        """创建子部门前锁定父行并校验层级与启用状态。"""
        if parent_id is None:
            return None
        parent = self._uow.departments.get_for_update(parent_id, tenant_id)
        if parent is None:
            raise NotFoundError("上级部门不存在")
        if not parent.is_active:
            raise ValidationError("上级部门已停用，不能在其下新建部门")
        if parent.level >= _MAX_LEVEL:
            raise ValidationError("部门层级最多 10 级")
        return parent

    def _get_owned(self, department_id: UUID, tenant_id: UUID) -> Department:
        department = self._uow.departments.get(department_id)
        if department is None or department.tenant_id != tenant_id:
            raise NotFoundError("部门不存在")
        return department

    def _require_tenant(self) -> UUID:
        if self._context.is_platform:
            raise ForbiddenError("组织架构仅可由租户平台维护")
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
        """写入部门操作审计记录。"""
        record_audit(
            self._uow,
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="department",
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


def _build_path(parent: Department | None, department_id: UUID) -> str:
    """根部门路径 /<id>/，子部门路径为父路径拼接 <id>/。"""
    if parent is None:
        return f"/{department_id}/"
    return f"{parent.path}{department_id}/"
