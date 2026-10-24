"""工具管理接口。"""

from fastapi import APIRouter, Depends, Query, Request, status

from web.admin.schemas.common import PageOut
from web.admin.schemas.resource import ResourceCloneRequest, ToolOut, ToolPayload
from web.deps.auth import EditorAuthDep, require_editor
from web.deps.http import client_meta
from web.deps.services import ToolServiceDep

router = APIRouter(prefix="/tools", tags=["admin-tools"])


@router.get("", response_model=PageOut[ToolOut])
def list_tools(
    service: ToolServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
    agent_id: int | None = Query(None, ge=1),
) -> PageOut[ToolOut]:
    """分页查询工具；agent_id 限定所属智能体。"""
    result = service.list(page, page_size, keyword, is_enabled, agent_id)
    return PageOut[ToolOut](
        items=[ToolOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    response_model=ToolOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_tool(payload: ToolPayload, service: ToolServiceDep) -> ToolOut:
    """创建工具。"""
    return ToolOut.model_validate(service.create(payload.model_dump()))


@router.get("/{tool_id}", response_model=ToolOut)
def get_tool(tool_id: int, service: ToolServiceDep) -> ToolOut:
    """查询工具详情。"""
    return ToolOut.model_validate(service.get(tool_id))


@router.put("/{tool_id}", response_model=ToolOut, dependencies=[Depends(require_editor)])
def update_tool(tool_id: int, payload: ToolPayload, service: ToolServiceDep) -> ToolOut:
    """更新工具。"""
    return ToolOut.model_validate(service.update(tool_id, payload.model_dump()))


@router.delete(
    "/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_tool(tool_id: int, service: ToolServiceDep) -> None:
    """删除工具。"""
    service.delete(tool_id)


@router.post(
    "/{tool_id}/clone",
    response_model=ToolOut,
    status_code=status.HTTP_201_CREATED,
)
def clone_tool(
    tool_id: int,
    payload: ResourceCloneRequest,
    principal: EditorAuthDep,
    request: Request,
    service: ToolServiceDep,
) -> ToolOut:
    """把工具克隆到目标智能体，生成独立副本。"""
    ip, user_agent = client_meta(request)
    clone = service.clone_to_agent(
        tool_id,
        agent_id=payload.agent_id,
        name=payload.name,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return ToolOut.model_validate(clone)
