"""用户端登录、刷新与登出接口。"""

from fastapi import APIRouter, Request, status

from internal.application.errors import ForbiddenError
from web.deps.auth import UserAuthDep
from web.deps.http import client_meta
from web.deps.services import UserAuthServiceDep
from web.deps.tenant import RequestContextDep
from web.user.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, UserOut

router = APIRouter(prefix="/auth", tags=["user-auth"])


def _build_response(pair) -> LoginResponse:
    return LoginResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        refresh_expires_in=pair.refresh_expires_in,
        user=UserOut.model_validate(pair.user),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    service: UserAuthServiceDep,
    context: RequestContextDep,
) -> LoginResponse:
    """最终用户登录，仅支持租户子域名。"""
    if context.is_platform:
        raise ForbiddenError("用户端仅支持通过租户子域名访问")
    ip, user_agent = client_meta(request)
    pair = service.login(
        payload.username,
        payload.password,
        tenant_id=context.tenant_id,
        ip=ip,
        user_agent=user_agent,
    )
    return _build_response(pair)


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    payload: RefreshRequest,
    request: Request,
    service: UserAuthServiceDep,
    context: RequestContextDep,
) -> LoginResponse:
    """轮换刷新令牌，令牌租户必须与当前子域名一致。"""
    if context.is_platform:
        raise ForbiddenError("用户端仅支持通过租户子域名访问")
    ip, user_agent = client_meta(request)
    pair = service.refresh(
        payload.refresh_token,
        tenant_id=context.tenant_id,
        ip=ip,
        user_agent=user_agent,
    )
    return _build_response(pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    principal: UserAuthDep,
    request: Request,
    service: UserAuthServiceDep,
) -> None:
    """撤销当前会话族，使访问令牌立即失效。"""
    ip, user_agent = client_meta(request)
    service.logout(
        principal.user_id,
        principal.username,
        principal.tenant_id,
        principal.session_id,
        ip=ip,
        user_agent=user_agent,
    )
