"""技能管理接口。"""

from fastapi import APIRouter, Depends, Query, status

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Skill
from web.admin.schemas import PageOut, SkillOut, SkillPayload
from web.deps.auth import require_editor
from web.deps.services import SkillServiceDep

router = APIRouter(prefix="/skills", tags=["admin-skills"])


@router.get("", response_model=PageOut[SkillOut])
def list_skills(
    service: SkillServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
) -> PageOut[SkillOut]:
    """分页查询技能。"""
    result = service.list(page, page_size, keyword, is_enabled)
    return _to_page_out(result)


@router.post(
    "",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_skill(payload: SkillPayload, service: SkillServiceDep) -> SkillOut:
    """创建技能。"""
    return SkillOut.model_validate(service.create(payload.model_dump()))


@router.get("/{skill_id}", response_model=SkillOut)
def get_skill(skill_id: int, service: SkillServiceDep) -> SkillOut:
    """查询技能详情。"""
    return SkillOut.model_validate(service.get(skill_id))


@router.put("/{skill_id}", response_model=SkillOut, dependencies=[Depends(require_editor)])
def update_skill(skill_id: int, payload: SkillPayload, service: SkillServiceDep) -> SkillOut:
    """更新技能。"""
    return SkillOut.model_validate(service.update(skill_id, payload.model_dump()))


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_skill(skill_id: int, service: SkillServiceDep) -> None:
    """删除技能。"""
    service.delete(skill_id)


def _to_page_out(result: Page[Skill]) -> PageOut[SkillOut]:
    return PageOut[SkillOut](
        items=[SkillOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
