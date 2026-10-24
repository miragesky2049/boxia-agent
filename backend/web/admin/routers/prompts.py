"""提示词管理接口。"""

from fastapi import APIRouter, Depends, Query, Request, status

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Prompt
from web.admin.schemas.common import PageOut
from web.admin.schemas.resource import PromptOut, PromptPayload, ResourceCloneRequest
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import PromptServiceDep

router = APIRouter(prefix="/prompts", tags=["admin-prompts"])


@router.get(
    "",
    response_model=PageOut[PromptOut],
    dependencies=[Depends(require_permission("prompt:read"))],
)
def list_prompts(
    service: PromptServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
    agent_id: int | None = Query(None, ge=1),
) -> PageOut[PromptOut]:
    """分页查询提示词；agent_id 限定所属智能体。"""
    result = service.list(page, page_size, keyword, is_enabled, agent_id)
    return _to_page_out(result)


@router.post(
    "",
    response_model=PromptOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("prompt:create"))],
)
def create_prompt(
    payload: PromptPayload,
    principal: AdminAuthDep,
    service: PromptServiceDep,
) -> PromptOut:
    """创建提示词，并授权给创建者角色。"""
    return PromptOut.model_validate(service.create(payload.model_dump(), principal.role_ids))


@router.get(
    "/{prompt_id}",
    response_model=PromptOut,
    dependencies=[Depends(require_permission("prompt:read"))],
)
def get_prompt(prompt_id: int, service: PromptServiceDep) -> PromptOut:
    """查询提示词详情。"""
    return PromptOut.model_validate(service.get(prompt_id))


@router.put(
    "/{prompt_id}",
    response_model=PromptOut,
    dependencies=[Depends(require_permission("prompt:update"))],
)
def update_prompt(prompt_id: int, payload: PromptPayload, service: PromptServiceDep) -> PromptOut:
    """更新提示词。"""
    return PromptOut.model_validate(service.update(prompt_id, payload.model_dump()))


@router.delete(
    "/{prompt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("prompt:delete"))],
)
def delete_prompt(prompt_id: int, service: PromptServiceDep) -> None:
    """删除提示词。"""
    service.delete(prompt_id)


@router.post(
    "/{prompt_id}/clone",
    response_model=PromptOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("prompt:create"))],
)
def clone_prompt(
    prompt_id: int,
    payload: ResourceCloneRequest,
    principal: AdminAuthDep,
    request: Request,
    service: PromptServiceDep,
) -> PromptOut:
    """把提示词克隆到目标智能体，生成独立副本。"""
    ip, user_agent = client_meta(request)
    clone = service.clone_to_agent(
        prompt_id,
        agent_id=payload.agent_id,
        name=payload.name,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_ids=principal.role_ids,
        ip=ip,
        user_agent=user_agent,
    )
    return PromptOut.model_validate(clone)


def _to_page_out(result: Page[Prompt]) -> PageOut[PromptOut]:
    return PageOut[PromptOut](
        items=[PromptOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
