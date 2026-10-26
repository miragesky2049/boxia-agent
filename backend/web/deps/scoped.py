"""按调用者角色收敛资源可见性的工作单元依赖（含行级数据范围叠加）。"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from internal.domain.entity.permission import DATA_ALL
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
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
    """用户端作用域工作单元：按本人全部角色合并过滤（本期不叠加行级数据范围）。"""
    uow.apply_scope(principal.role_ids or (principal.role_id,), True)
    return uow


AdminScopedUowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_admin_scoped_uow)]
UserScopedUowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_user_scoped_uow)]
