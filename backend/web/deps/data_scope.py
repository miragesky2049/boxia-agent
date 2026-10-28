"""行级数据范围快照组装：把当前调用者被授权的管理单元展开为部门/人员 id 集合。

展开规则：
- 平台账号或拥有 system:data:all 权限：返回 None（不叠加行过滤）
- 否则：查 user_mgmt_unit_grants → 取所有关联部门（含子树开关）和人员 → 组装 UserDataScope
- 未被授权任何管理单元：is_empty=True，行过滤仅本人创建
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from internal.domain.entity.data_scope import UserDataScope
from internal.domain.entity.permission import DATA_ALL
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from web.deps.auth import AdminAuthDep
from web.deps.db import UowDep


def build_data_scope_snapshot(uow: UowDep, principal: AdminAuthDep) -> UserDataScope | None:
    """组装 UserDataScope；平台账号或拥有全量数据权限时返回 None（不叠加行过滤）。"""
    if principal.is_platform:
        return None
    if DATA_ALL in principal.permissions:
        return None

    tenant_id = principal.tenant_id
    user_id = principal.user_id

    # 1) 查用户被授权的管理单元 id 集合
    unit_ids = uow.user_mgmt_unit_grants.list_unit_ids_for_user(tenant_id, user_id)
    if not unit_ids:
        # 未授权任何管理单元：fail-closed，仅本人创建
        return UserDataScope(tenant_id=tenant_id, user_id=user_id)

    # 2) 批量读取单元的部门关联和人员关联
    unit_id_list = sorted(unit_ids)
    dept_bindings = uow.mgmt_units.list_departments_for_units(unit_id_list)
    user_bindings = uow.mgmt_units.list_users_for_units(unit_id_list)

    # 3) 展开部门：include_subtree=True 的部门需要包含其全部下级
    visible_department_ids: set[UUID] = set()
    direct_dept_ids: set[UUID] = set()
    subtree_dept_ids: set[UUID] = set()
    for binding in dept_bindings:
        if binding.include_subtree:
            subtree_dept_ids.add(binding.department_id)
        else:
            direct_dept_ids.add(binding.department_id)
    visible_department_ids.update(direct_dept_ids)
    if subtree_dept_ids:
        visible_department_ids.update(
            _expand_department_subtrees(uow, tenant_id, subtree_dept_ids)
        )

    # 4) 人员集合直接收集
    visible_user_ids = {binding.user_id for binding in user_bindings}

    return UserDataScope(
        tenant_id=tenant_id,
        user_id=user_id,
        visible_department_ids=frozenset(visible_department_ids),
        visible_user_ids=frozenset(visible_user_ids),
    )


def _expand_department_subtrees(
    uow: SqlAlchemyUnitOfWork, tenant_id: UUID, root_dept_ids: set[UUID]
) -> set[UUID]:
    """按部门物化路径前缀，把每个根部门展开为自身 + 全部下级部门 id 集合。"""
    if not root_dept_ids:
        return set()
    # 读取全部部门（租户内部门数量通常有限，内存展开简单高效）
    all_departments = uow.departments.list_all(tenant_id)
    # 建立 id -> path 映射，并构建 id 集合
    dept_id_to_path = {dept.id: dept.path for dept in all_departments}
    root_paths = {dept_id_to_path[dept_id] for dept_id in root_dept_ids if dept_id in dept_id_to_path}
    if not root_paths:
        return set()
    result: set[UUID] = set()
    for dept in all_departments:
        if any(dept.path.startswith(root_path) for root_path in root_paths):
            result.add(dept.id)
    return result


DataScopeSnapshotDep = Annotated[UserDataScope | None, Depends(build_data_scope_snapshot)]
