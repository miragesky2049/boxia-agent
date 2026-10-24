"""技能管理接口。"""

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from internal.domain.entity.common import Page
from internal.domain.entity.resource import Skill
from web.admin.schemas.common import PageOut
from web.admin.schemas.resource import SkillOut, SkillPayload
from web.admin.schemas.skill_package import (
    SkillCloneRequest,
    SkillFileListOut,
    SkillFileMetaOut,
    SkillFileOut,
    SkillFileWriteRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import SkillPackageServiceDep, SkillServiceDep

router = APIRouter(prefix="/skills", tags=["admin-skills"])


@router.get(
    "",
    response_model=PageOut[SkillOut],
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_skills(
    service: SkillServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
    agent_id: int | None = Query(None, ge=1),
) -> PageOut[SkillOut]:
    """分页查询技能；agent_id 限定所属智能体。"""
    result = service.list(page, page_size, keyword, is_enabled, agent_id)
    return _to_page_out(result)


@router.post(
    "",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("skill:create"))],
)
def create_skill(
    payload: SkillPayload,
    principal: AdminAuthDep,
    service: SkillServiceDep,
) -> SkillOut:
    """创建技能，并授权给创建者角色。"""
    return SkillOut.model_validate(service.create(payload.model_dump(), principal.role_ids))


@router.get(
    "/{skill_id}",
    response_model=SkillOut,
    dependencies=[Depends(require_permission("skill:read"))],
)
def get_skill(skill_id: int, service: SkillServiceDep) -> SkillOut:
    """查询技能详情。"""
    return SkillOut.model_validate(service.get(skill_id))


@router.put(
    "/{skill_id}",
    response_model=SkillOut,
    dependencies=[Depends(require_permission("skill:update"))],
)
def update_skill(skill_id: int, payload: SkillPayload, service: SkillServiceDep) -> SkillOut:
    """更新技能。"""
    return SkillOut.model_validate(service.update(skill_id, payload.model_dump()))


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("skill:delete"))],
)
def delete_skill(skill_id: int, service: SkillServiceDep) -> None:
    """删除技能（包内文件随外键级联删除）。"""
    service.delete(skill_id)


@router.get(
    "/{skill_id}/files",
    response_model=SkillFileListOut,
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_skill_files(
    skill_id: int,
    service: SkillPackageServiceDep,
    prefix: str | None = Query(None, max_length=512),
) -> SkillFileListOut:
    """列出技能包内文件（不含正文）。"""
    files = service.list_files(skill_id, prefix)
    items = [SkillFileMetaOut.model_validate(file) for file in files]
    return SkillFileListOut(
        items=items,
        total=len(items),
        total_bytes=sum(file.size_bytes for file in files),
    )


@router.get(
    "/{skill_id}/files/content",
    response_model=SkillFileOut,
    dependencies=[Depends(require_permission("skill:read"))],
)
def read_skill_file(
    skill_id: int,
    service: SkillPackageServiceDep,
    path: str = Query(..., min_length=1, max_length=512),
) -> SkillFileOut:
    """读取技能包内单个文件。"""
    return SkillFileOut.model_validate(service.read_file(skill_id, path))


@router.put(
    "/{skill_id}/files",
    response_model=SkillFileOut,
    dependencies=[Depends(require_permission("skill:update"))],
)
def write_skill_file(
    skill_id: int,
    payload: SkillFileWriteRequest,
    service: SkillPackageServiceDep,
) -> SkillFileOut:
    """新增或覆盖技能包文件；写 SKILL.md 会同步技能入口内容。"""
    file = service.write_file(
        skill_id,
        path=payload.path,
        content=payload.content,
        expected_hash=payload.expected_hash,
    )
    return SkillFileOut.model_validate(file)


@router.delete(
    "/{skill_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("skill:update"))],
)
def delete_skill_file(
    skill_id: int,
    service: SkillPackageServiceDep,
    path: str = Query(..., min_length=1, max_length=512),
) -> None:
    """删除技能包文件。"""
    service.delete_file(skill_id, path)


@router.post(
    "/{skill_id}/import",
    response_model=list[SkillFileMetaOut],
    dependencies=[Depends(require_permission("skill:update"))],
)
def import_skill_package(
    skill_id: int,
    service: SkillPackageServiceDep,
    body: bytes = Body(..., media_type="application/zip"),
) -> list[SkillFileMetaOut]:
    """上传 zip 技能包并全量替换包内文件。"""
    return [SkillFileMetaOut.model_validate(file) for file in service.import_zip(skill_id, body)]


@router.get(
    "/{skill_id}/export",
    dependencies=[Depends(require_permission("skill:read"))],
)
def export_skill_package(skill_id: int, service: SkillPackageServiceDep) -> Response:
    """导出技能包为 zip。"""
    data = service.export_zip(skill_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="skill-{skill_id}.zip"'},
    )


@router.post(
    "/{skill_id}/clone",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("skill:create"))],
)
def clone_skill(
    skill_id: int,
    payload: SkillCloneRequest,
    principal: AdminAuthDep,
    request: Request,
    service: SkillServiceDep,
    package_service: SkillPackageServiceDep,
) -> SkillOut:
    """指定 agent_id 时克隆到目标智能体；否则克隆到当前租户。"""
    if payload.agent_id is None:
        return SkillOut.model_validate(
            package_service.clone_to_current_tenant(
                skill_id, payload.name, principal.role_ids
            )
        )
    ip, user_agent = client_meta(request)
    clone = service.clone_to_agent(
        skill_id,
        agent_id=payload.agent_id,
        name=payload.name,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_ids=principal.role_ids,
        ip=ip,
        user_agent=user_agent,
    )
    return SkillOut.model_validate(clone)


def _to_page_out(result: Page[Skill]) -> PageOut[SkillOut]:
    return PageOut[SkillOut](
        items=[SkillOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
