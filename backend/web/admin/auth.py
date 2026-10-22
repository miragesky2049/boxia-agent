"""管理端登录、刷新、登出、改密与当前用户接口。"""

from fastapi import APIRouter, Request, status

from web.admin.schemas import (
    AdminUserOut,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
)
from web.deps.auth import AdminAuthDep
from web.deps.services import AuthServiceDep

login_router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent


@login_router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, service: AuthServiceDep) -> LoginResponse:
    """管理员登录，返回访问令牌与刷新令牌。"""
    ip, user_agent = _client_meta(request)
    pair = service.login(payload.username, payload.password, ip=ip, user_agent=user_agent)
    return LoginResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        refresh_expires_in=pair.refresh_expires_in,
        user=AdminUserOut.model_validate(pair.user),
    )


@login_router.post("/refresh", response_model=LoginResponse)
def refresh(payload: RefreshRequest, request: Request, service: AuthServiceDep) -> LoginResponse:
    """轮换刷新令牌并签发新的访问令牌。"""
    ip, user_agent = _client_meta(request)
    pair = service.refresh(payload.refresh_token, ip=ip, user_agent=user_agent)
    return LoginResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        refresh_expires_in=pair.refresh_expires_in,
        user=AdminUserOut.model_validate(pair.user),
    )


@login_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: AdminAuthDep, request: Request, service: AuthServiceDep) -> None:
    """撤销当前会话族，使访问令牌立即失效。"""
    ip, user_agent = _client_meta(request)
    user = service.get_profile(principal.user_id)
    service.logout(user, principal.session_id, ip=ip, user_agent=user_agent)


@login_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    principal: AdminAuthDep,
    request: Request,
    service: AuthServiceDep,
) -> None:
    """修改当前账号密码并撤销全部会话。"""
    ip, user_agent = _client_meta(request)
    service.change_password(
        principal.user_id,
        payload.current_password,
        payload.new_password,
        ip=ip,
        user_agent=user_agent,
    )


@login_router.get("/me", response_model=AdminUserOut)
def get_current_admin(principal: AdminAuthDep, service: AuthServiceDep) -> AdminUserOut:
    """返回当前登录的管理员信息。"""
    return AdminUserOut.model_validate(service.get_profile(principal.user_id))
