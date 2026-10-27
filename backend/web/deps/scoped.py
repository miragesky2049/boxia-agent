"""按调用者角色收敛资源可见性的工作单元依赖（含行级数据范围叠加）。"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from internal.domain.entity.permission import DATA_ALL
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.agent_user_visibility_filter import (
    UserAgentVisibilityContext,
)
from web.deps.auth import AdminAuthDep, AdminPrincipal, UserAuthDep
from web.deps.data_scope import build_data_scope_snapshot
from web.deps.db import UowDep


def _admin_scope(principal: AdminPrincipal) -> tuple[tuple[UUID, ...], bool]:
    """拥有全量数据权限的角色不做资源过滤，其余按全部角色授权收敛。"""
    if DATA_ALL in principal.permissions:
        return (), False
    return principal.role_ids, True


def get_admin_scoped_uow(
    uow: UowDep,
    principal: AdminAuthDep,
) -> SqlAlchemyUnitOfWork:
    """管理端作用域工作单元：按角色收敛实例授权，并叠加行级数据权限过滤。"""
    role_ids, apply_role_filter = _admin_scope(principal)
    uow.apply_scope(role_ids, apply_role_filter)
    # 平台账号或拥有全量数据权限时快照为 None，不叠加行过滤
    snapshot = build_data_scope_snapshot(uow, principal)
    uow.apply_data_scope(snapshot)
    return uow


def get_user_scoped_uow(uow: UowDep, principal: UserAuthDep) -> SqlAlchemyUnitOfWork:
    """用户端作用域工作单元：按本人角色收敛，并叠加智能体实例级可见范围。"""
    uow.apply_scope(principal.role_ids or (principal.role_id,), True)
    # 注入当前用户的实例级可见范围：当前任职部门 id + path（无任职则仅按 user_id 命中）
    brief = uow.employments.get_current_department_brief(
        principal.tenant_id, principal.user_id
    )
    context = UserAgentVisibilityContext(
        current_user_id=principal.user_id,
        current_department_id=brief[0] if brief else None,
        current_department_path=brief[1] if brief else None,
    )
    uow.apply_user_visibility(context)
    return uow


AdminScopedUowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_admin_scoped_uow)]
UserScopedUowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_user_scoped_uow)]
