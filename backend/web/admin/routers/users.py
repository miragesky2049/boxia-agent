"""租户最终用户管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from internal.domain.entity.access import User
from internal.domain.entity.common import Page
from web.admin.schemas.common import PageOut
from web.admin.schemas.user import (
    UserCreateRequest,
    UserOut,
    UserResetPasswordRequest,
    UserUpdateRequest,
)
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.http import client_meta
from web.deps.services import UserAdminServiceDep

router = APIRouter(prefix="/users", tags=["admin-users"])


@router.get(
    "",
    response_model=PageOut[UserOut],
    dependencies=[Depends(require_permission("page:users"))],
)
def list_users(
    service: UserAdminServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    department_id: UUID | None = Query(None),
) -> PageOut[UserOut]:
    """分页查询本租户最终用户，department_id 非空时按部门（含下级）筛选。"""
    return _to_page_out(service.list(page, page_size, keyword, department_id))


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("button:user:create"))],
)
def create_user(
    payload: UserCreateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: UserAdminServiceDep,
) -> UserOut:
    """创建最终用户并绑定本租户角色。"""
    ip, user_agent = client_meta(request)
    user = service.create(
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role_ids=payload.role_ids,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return UserOut.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permission("button:user:update"))],
)
def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    principal: AdminAuthDep,
    request: Request,
    service: UserAdminServiceDep,
) -> UserOut:
    """更新最终用户；禁用或改角色会撤销其全部会话。"""
    ip, user_agent = client_meta(request)
    user = service.update(
        user_id,
        display_name=payload.display_name,
        role_ids=payload.role_ids,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return UserOut.model_validate(user)


@router.post(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:user:update"))],
)
def reset_user_password(
    user_id: UUID,
    payload: UserResetPasswordRequest,
    principal: AdminAuthDep,
    request: Request,
    service: UserAdminServiceDep,
) -> None:
    """重置最终用户密码并撤销其全部会话。"""
    ip, user_agent = client_meta(request)
    service.reset_password(
        user_id,
        new_password=payload.new_password,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("button:user:delete"))],
)
def delete_user(
    user_id: UUID,
    principal: AdminAuthDep,
    request: Request,
    service: UserAdminServiceDep,
) -> None:
    """删除最终用户。"""
    ip, user_agent = client_meta(request)
    service.delete(
        user_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


def _to_page_out(result: Page[User]) -> PageOut[UserOut]:
    return PageOut[UserOut](
        items=[UserOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
