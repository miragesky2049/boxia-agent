"""用户任职记录管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from internal.domain.entity.common import Page
from internal.domain.entity.employment import Employment
from web.admin.schemas.common import PageOut
from web.admin.schemas.employment import (
    EmploymentArchiveRequest,
    EmploymentCreateRequest,
    EmploymentOut,
    EmploymentTransferRequest,
    EmploymentUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import EmploymentServiceDep

router = APIRouter(prefix="/employments", tags=["admin-employments"])


@router.get(
    "",
    response_model=PageOut[EmploymentOut],
    dependencies=[Depends(require_permission("page:employments"))],
)
def list_employments(
    service: EmploymentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    department_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    is_current: bool | None = Query(None),
) -> PageOut[EmploymentOut]:
    """分页查询任职记录，部门筛选含下级部门。"""
    result = service.list(page, page_size, keyword, department_id, user_id, is_current)
    return _to_page_out(result)


@router.post(
    "",
    response_model=EmploymentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:employment:create"))],
)
def create_employment(
    payload: EmploymentCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EmploymentServiceDep,
) -> EmploymentOut:
    """新增用户当前任职。"""
    ip, user_agent = client_meta(request)
    employment = service.create(
        user_id=payload.user_id,
        department_id=payload.department_id,
        position=payload.position,
        started_at=payload.started_at,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EmploymentOut.model_validate(employment)


@router.patch(
    "/{employment_id}",
    response_model=EmploymentOut,
    dependencies=[Depends(require_permission("button:employment:update"))],
)
def update_employment(
    employment_id: UUID,
    payload: EmploymentUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EmploymentServiceDep,
) -> EmploymentOut:
    """更新任职岗位或生效日期。"""
    ip, user_agent = client_meta(request)
    employment = service.update(
        employment_id,
        position=payload.position,
        started_at=payload.started_at,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EmploymentOut.model_validate(employment)


@router.post(
    "/{employment_id}/transfer",
    response_model=EmploymentOut,
    dependencies=[Depends(require_permission("button:employment:update"))],
)
def transfer_employment(
    employment_id: UUID,
    payload: EmploymentTransferRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EmploymentServiceDep,
) -> EmploymentOut:
    """调岗：归档原任职并生成新的当前任职。"""
    ip, user_agent = client_meta(request)
    employment = service.transfer(
        employment_id,
        department_id=payload.department_id,
        position=payload.position,
        started_at=payload.started_at,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EmploymentOut.model_validate(employment)


@router.post(
    "/{employment_id}/archive",
    response_model=EmploymentOut,
    dependencies=[Depends(require_permission("button:employment:update"))],
)
def archive_employment(
    employment_id: UUID,
    payload: EmploymentArchiveRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EmploymentServiceDep,
) -> EmploymentOut:
    """结束当前任职。"""
    ip, user_agent = client_meta(request)
    employment = service.archive(
        employment_id,
        ended_at=payload.ended_at,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EmploymentOut.model_validate(employment)


@router.delete(
    "/{employment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:employment:delete"))],
)
def delete_employment(
    employment_id: UUID,
    principal: AdminAuthDep,
    request: Request,
    service: EmploymentServiceDep,
) -> None:
    """物理删除任职记录。"""
    ip, user_agent = client_meta(request)
    service.delete(
        employment_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


def _to_page_out(result: Page[Employment]) -> PageOut[EmploymentOut]:
    return PageOut[EmploymentOut](
        items=[EmploymentOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
