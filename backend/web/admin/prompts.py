"""提示词管理接口。"""

from fastapi import APIRouter, Depends, Query, status

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Prompt
from web.admin.schemas import PageOut, PromptOut, PromptPayload
from web.deps.auth import require_editor
from web.deps.services import PromptServiceDep

router = APIRouter(prefix="/prompts", tags=["admin-prompts"])


@router.get("", response_model=PageOut[PromptOut])
def list_prompts(
    service: PromptServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
) -> PageOut[PromptOut]:
    """分页查询提示词。"""
    result = service.list(page, page_size, keyword, is_enabled)
    return _to_page_out(result)


@router.post(
    "",
    response_model=PromptOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_prompt(payload: PromptPayload, service: PromptServiceDep) -> PromptOut:
    """创建提示词。"""
    return PromptOut.model_validate(service.create(payload.model_dump()))


@router.get("/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: int, service: PromptServiceDep) -> PromptOut:
    """查询提示词详情。"""
    return PromptOut.model_validate(service.get(prompt_id))


@router.put(
    "/{prompt_id}",
    response_model=PromptOut,
    dependencies=[Depends(require_editor)],
)
def update_prompt(prompt_id: int, payload: PromptPayload, service: PromptServiceDep) -> PromptOut:
    """更新提示词。"""
    return PromptOut.model_validate(service.update(prompt_id, payload.model_dump()))


@router.delete(
    "/{prompt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_prompt(prompt_id: int, service: PromptServiceDep) -> None:
    """删除提示词。"""
    service.delete(prompt_id)


def _to_page_out(result: Page[Prompt]) -> PageOut[PromptOut]:
    return PageOut[PromptOut](
        items=[PromptOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
