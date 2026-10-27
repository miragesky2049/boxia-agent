"""HR 字典管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from web.admin.schemas.hr_dictionary import (
    HrDictionaryCreateRequest,
    HrDictionaryOut,
    HrDictionaryUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import HrDictionaryServiceDep

router = APIRouter(prefix="/hr-dictionaries", tags=["admin-hr-dictionaries"])


@router.get(
    "",
    response_model=list[HrDictionaryOut],
    dependencies=[Depends(require_permission("page:employments"))],
)
def list_dictionaries(
    service: HrDictionaryServiceDep,
    category: str = Query(..., max_length=32),
    include_inactive: bool = Query(False),
) -> list[HrDictionaryOut]:
    """按类别读取租户字典项。"""
    items = service.list(category, include_inactive=include_inactive)
    return [HrDictionaryOut.model_validate(item) for item in items]


@router.post(
    "",
    response_model=HrDictionaryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:employment:update"))],
)
def create_dictionary(
    payload: HrDictionaryCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: HrDictionaryServiceDep,
) -> HrDictionaryOut:
    """新建字典项。"""
    ip, user_agent = client_meta(request)
    item = service.create(
        category=payload.category,
        code=payload.code,
        name=payload.name,
        sort_order=payload.sort_order,
        remark=payload.remark,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return HrDictionaryOut.model_validate(item)


@router.patch(
    "/{dictionary_id}",
    response_model=HrDictionaryOut,
    dependencies=[Depends(require_permission("button:employment:update"))],
)
def update_dictionary(
    dictionary_id: UUID,
    payload: HrDictionaryUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: HrDictionaryServiceDep,
) -> HrDictionaryOut:
    """更新字典项基础字段。"""
    ip, user_agent = client_meta(request)
    item = service.update(
        dictionary_id,
        name=payload.name,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        remark=payload.remark,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return HrDictionaryOut.model_validate(item)


@router.delete(
    "/{dictionary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:employment:delete"))],
)
def delete_dictionary(
    dictionary_id: UUID,
    principal: AdminAuthDep,
    request: Request,
    service: HrDictionaryServiceDep,
) -> None:
    """删除字典项；仍被任职记录引用时拒绝。"""
    ip, user_agent = client_meta(request)
    service.delete(
        dictionary_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
