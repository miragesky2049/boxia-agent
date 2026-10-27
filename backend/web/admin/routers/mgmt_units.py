"""管理单元管理接口。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from internal.domain.entity.mgmt_unit import ManagementUnit
from web.admin.schemas.mgmt_unit import (
    MgmtUnitCreateRequest,
    MgmtUnitDepartmentsReplaceRequest,
    MgmtUnitDepartmentOut,
    MgmtUnitOut,
    MgmtUnitUpdateRequest,
    MgmtUnitUsersReplaceRequest,
    MgmtUnitUserOut,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import MgmtUnitServiceDep

router = APIRouter(prefix="/mgmt-units", tags=["admin-mgmt-units"])


@router.get(
    "",
    response_model=list[MgmtUnitOut],
    dependencies=[Depends(require_permission("page:mgmt-units"))],
)
def list_mgmt_units(service: MgmtUnitServiceDep) -> list[MgmtUnitOut]:
    """返回本租户管理单元树。"""
    return _build_tree(service.list_tree())


@router.get(
    "/active",
    response_model=list[MgmtUnitOut],
    dependencies=[Depends(require_permission("page:mgmt-units"))],
)
def list_active_mgmt_units(service: MgmtUnitServiceDep) -> list[MgmtUnitOut]:
    """返回启用中的管理单元列表（授权弹窗勾选用，不组装树）。"""
    return [MgmtUnitOut.model_validate(unit) for unit in service.list_active_units()]


@router.post(
    "",
    response_model=MgmtUnitOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:mgmt-unit:create"))],
)
def create_mgmt_unit(
    payload: MgmtUnitCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: MgmtUnitServiceDep,
) -> MgmtUnitOut:
    """创建管理单元。"""
    ip, user_agent = client_meta(request)
    unit = service.create(
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        sort_order=payload.sort_order,
        attrs=payload.attrs,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return MgmtUnitOut.model_validate(unit)


@router.patch(
    "/{unit_id}",
    response_model=MgmtUnitOut,
    dependencies=[Depends(require_permission("button:mgmt-unit:update"))],
)
def update_mgmt_unit(
    unit_id: UUID,
    payload: MgmtUnitUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: MgmtUnitServiceDep,
) -> MgmtUnitOut:
    """更新管理单元；parent_id 变化时移动子树。"""
    ip, user_agent = client_meta(request)
    unit = service.update(
        unit_id,
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        sort_order=payload.sort_order,
        attrs=payload.attrs,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return MgmtUnitOut.model_validate(unit)


@router.delete(
    "/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:mgmt-unit:delete"))],
)
def delete_mgmt_unit(
    unit_id: UUID,
    principal: AdminAuthDep,
    request: Request,
    service: MgmtUnitServiceDep,
) -> None:
    """物理删除管理单元；存在引用时返回 409。"""
    ip, user_agent = client_meta(request)
    service.delete(
        unit_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.get(
    "/{unit_id}/departments",
    response_model=list[MgmtUnitDepartmentOut],
    dependencies=[Depends(require_permission("button:mgmt-unit:update"))],
)
def list_mgmt_unit_departments(
    unit_id: UUID,
    service: MgmtUnitServiceDep,
) -> list[MgmtUnitDepartmentOut]:
    """读取管理单元已关联部门。"""
    items = service.list_departments(unit_id)
    return [MgmtUnitDepartmentOut.model_validate(item) for item in items]


@router.put(
    "/{unit_id}/departments",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:mgmt-unit:update"))],
)
def replace_mgmt_unit_departments(
    unit_id: UUID,
    payload: MgmtUnitDepartmentsReplaceRequest,
    principal: AdminAuthDep,
    request: Request,
    service: MgmtUnitServiceDep,
) -> None:
    """整体替换管理单元的部门关联。"""
    ip, user_agent = client_meta(request)
    bindings = [(item.department_id, item.include_subtree) for item in payload.bindings]
    service.replace_departments(
        unit_id,
        bindings,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.get(
    "/{unit_id}/users",
    response_model=list[MgmtUnitUserOut],
    dependencies=[Depends(require_permission("button:mgmt-unit:update"))],
)
def list_mgmt_unit_users(
    unit_id: UUID,
    service: MgmtUnitServiceDep,
) -> list[MgmtUnitUserOut]:
    """读取管理单元已关联人员。"""
    items = service.list_users(unit_id)
    return [MgmtUnitUserOut.model_validate(item) for item in items]


@router.put(
    "/{unit_id}/users",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:mgmt-unit:update"))],
)
def replace_mgmt_unit_users(
    unit_id: UUID,
    payload: MgmtUnitUsersReplaceRequest,
    principal: AdminAuthDep,
    request: Request,
    service: MgmtUnitServiceDep,
) -> None:
    """整体替换管理单元的人员关联。"""
    ip, user_agent = client_meta(request)
    service.replace_users(
        unit_id,
        payload.user_ids,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


def _build_tree(units: list[ManagementUnit]) -> list[MgmtUnitOut]:
    """按 parent_id 在内存组装树，并按排序值与名称排序。"""
    nodes: dict[Any, MgmtUnitOut] = {item.id: MgmtUnitOut.model_validate(item) for item in units}
    roots: list[MgmtUnitOut] = []
    for item in units:
        node = nodes[item.id]
        if item.parent_id is None or item.parent_id not in nodes:
            roots.append(node)
        else:
            nodes[item.parent_id].children.append(node)

    def sort_children(node: MgmtUnitOut) -> None:
        node.children.sort(key=lambda child: (child.sort_order, child.name))
        for child in node.children:
            sort_children(child)

    roots.sort(key=lambda node: (node.sort_order, node.name))
    for node in roots:
        sort_children(node)
    return roots
