"""管理员账号管理接口（仅 superadmin）。"""

from fastapi import APIRouter, Depends, Query, Request, status

from web.admin.schemas.auth import (
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserResetPasswordRequest,
    AdminUserUpdateRequest,
)
from web.admin.schemas.common import PageOut
from web.deps.auth import AdminAuthDep, require_superadmin
from web.deps.services import AdminUserServiceDep

router = APIRouter(
    prefix="/admin-users",
    tags=["admin-accounts"],
    dependencies=[Depends(require_superadmin)],
)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent


@router.get("", response_model=PageOut[AdminUserOut])
def list_users(
    service: AdminUserServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
) -> PageOut[AdminUserOut]:
    """分页查询管理员：平台查平台账号，租户查拥有管理角色的用户。"""
    result = service.list(page, page_size, keyword)
    return PageOut[AdminUserOut](
        items=[AdminUserOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreateRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> AdminUserOut:
    """创建管理员账号，首次登录强制改密。"""
    ip, user_agent = _client_meta(request)
    user = service.create(
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
        role_id=payload.role_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return AdminUserOut.model_validate(user)


@router.patch("/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> AdminUserOut:
    """调整显示名、角色与启用状态。"""
    ip, user_agent = _client_meta(request)
    user = service.update(
        user_id,
        display_name=payload.display_name,
        role=payload.role,
        role_id=payload.role_id,
        is_active=payload.is_active,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return AdminUserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> None:
    """删除管理员账号并同步删除关联用户记录。"""
    ip, user_agent = _client_meta(request)
    service.delete(
        user_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: int,
    payload: AdminUserResetPasswordRequest,
    request: Request,
    service: AdminUserServiceDep,
    principal: AdminAuthDep,
) -> None:
    """重置管理员密码，强制下次登录改密。"""
    ip, user_agent = _client_meta(request)
    service.reset_password(
        user_id,
        new_password=payload.new_password,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
