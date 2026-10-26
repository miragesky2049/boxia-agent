"""部门管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from internal.domain.entity.department import Department
from web.admin.schemas.department import (
    DepartmentActiveRequest,
    DepartmentCreateRequest,
    DepartmentOut,
    DepartmentUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import DepartmentServiceDep

router = APIRouter(prefix="/departments", tags=["admin-departments"])


@router.get(
    "",
    response_model=list[DepartmentOut],
    dependencies=[Depends(require_permission("page:departments"))],
)
def list_departments(service: DepartmentServiceDep) -> list[DepartmentOut]:
    """返回本租户部门树。"""
    return _build_tree(service.list_tree())


@router.post(
    "",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:department:create"))],
)
def create_department(
    payload: DepartmentCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: DepartmentServiceDep,
) -> DepartmentOut:
    """创建部门。"""
    ip, user_agent = client_meta(request)
    department = service.create(
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return DepartmentOut.model_validate(department)


@router.patch(
    "/{department_id}",
    response_model=DepartmentOut,
    dependencies=[Depends(require_permission("button:department:update"))],
)
def update_department(
    department_id: UUID,
    payload: DepartmentUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: DepartmentServiceDep,
) -> DepartmentOut:
    """更新部门；parent_id 变化时移动子树。"""
    ip, user_agent = client_meta(request)
    department = service.update(
        department_id,
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        sort_order=payload.sort_order,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return DepartmentOut.model_validate(department)


@router.post(
    "/{department_id}/status",
    response_model=DepartmentOut,
    dependencies=[Depends(require_permission("button:department:update"))],
)
def set_department_active(
    department_id: UUID,
    payload: DepartmentActiveRequest,
    principal: AdminAuthDep,
    request: Request,
    service: DepartmentServiceDep,
) -> DepartmentOut:
    """停用或启用部门。"""
    ip, user_agent = client_meta(request)
    department = service.set_active(
        department_id,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return DepartmentOut.model_validate(department)


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:department:delete"))],
)
def delete_department(
    department_id: UUID,
    principal: AdminAuthDep,
    request: Request,
    service: DepartmentServiceDep,
) -> None:
    """物理删除部门；存在引用时返回 409。"""
    ip, user_agent = client_meta(request)
    service.delete(
        department_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


def _build_tree(departments: list[Department]) -> list[DepartmentOut]:
    """按 parent_id 在内存组装树，并按排序值与名称排序。"""
    nodes = {item.id: DepartmentOut.model_validate(item) for item in departments}
    roots: list[DepartmentOut] = []
    for item in departments:
        node = nodes[item.id]
        if item.parent_id is None or item.parent_id not in nodes:
            roots.append(node)
        else:
            nodes[item.parent_id].children.append(node)

    def sort_children(node: DepartmentOut) -> None:
        node.children.sort(key=lambda child: (child.sort_order, child.name))
        for child in node.children:
            sort_children(child)

    roots.sort(key=lambda node: (node.sort_order, node.name))
    for node in roots:
        sort_children(node)
    return roots
