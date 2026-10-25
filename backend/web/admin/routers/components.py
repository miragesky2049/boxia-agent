"""组件管理接口。"""

from fastapi import APIRouter, Depends, Query, Request, status

from internal.domain.entity.common import Page  # noqa: F401  (用于类型可读性)
from internal.domain.entity.resource import Component
from web.admin.schemas.common import PageOut
from web.admin.schemas.resource import (
    ComponentOut,
    ComponentPayload,
    ResourceCloneRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import ComponentServiceDep

router = APIRouter(prefix="/components", tags=["admin-components"])


@router.get(
    "",
    response_model=PageOut[ComponentOut],
    dependencies=[Depends(require_permission("component:read"))],
)
def list_components(
    service: ComponentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
    agent_id: int | None = Query(None, ge=1),
) -> PageOut[ComponentOut]:
    """分页查询组件；agent_id 限定所属智能体。"""
    result = service.list(page, page_size, keyword, is_enabled, agent_id)
    return _to_page_out(result)


@router.post(
    "",
    response_model=ComponentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("component:create"))],
)
def create_component(
    payload: ComponentPayload,
    principal: AdminAuthDep,
    service: ComponentServiceDep,
) -> ComponentOut:
    """创建组件，并授权给创建者角色。"""
    return ComponentOut.model_validate(
        service.create(payload.model_dump(), principal.role_ids)
    )


@router.get(
    "/{component_id}",
    response_model=ComponentOut,
    dependencies=[Depends(require_permission("component:read"))],
)
def get_component(component_id: int, service: ComponentServiceDep) -> ComponentOut:
    """查询组件详情。"""
    return ComponentOut.model_validate(service.get(component_id))


@router.put(
    "/{component_id}",
    response_model=ComponentOut,
    dependencies=[Depends(require_permission("component:update"))],
)
def update_component(
    component_id: int,
    payload: ComponentPayload,
    service: ComponentServiceDep,
) -> ComponentOut:
    """更新组件。"""
    return ComponentOut.model_validate(service.update(component_id, payload.model_dump()))


@router.delete(
    "/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("component:delete"))],
)
def delete_component(component_id: int, service: ComponentServiceDep) -> None:
    """删除组件。"""
    service.delete(component_id)


@router.post(
    "/{component_id}/clone",
    response_model=ComponentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("component:create"))],
)
def clone_component(
    component_id: int,
    payload: ResourceCloneRequest,
    principal: AdminAuthDep,
    request: Request,
    service: ComponentServiceDep,
) -> ComponentOut:
    """把组件克隆到目标智能体，生成独立副本。"""
    ip, user_agent = client_meta(request)
    clone = service.clone_to_agent(
        component_id,
        agent_id=payload.agent_id,
        name=payload.name,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_ids=principal.role_ids,
        ip=ip,
        user_agent=user_agent,
    )
    return ComponentOut.model_validate(clone)


def _to_page_out(result: Page[Component]) -> PageOut[ComponentOut]:
    return PageOut[ComponentOut](
        items=[ComponentOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
