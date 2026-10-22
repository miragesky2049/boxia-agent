"""admin 与 user 两套权限管控依赖。"""

import secrets
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from internal.application.errors import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from internal.domain.entity.admin_user import EDITOR_ROLES, AdminUser
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.observability.context import set_user_id
from web.deps.services import AuthServiceDep


@dataclass(frozen=True)
class AdminPrincipal:
    """管理端调用者身份（来自数据库校验后的访问上下文）。"""

    user_id: int
    username: str
    display_name: str
    role: str
    session_id: UUID


@dataclass(frozen=True)
class UserPrincipal:
    """用户端调用者身份（当前为静态令牌骨架）。"""

    subject: str


_bearer = HTTPBearer(auto_error=False)


def require_admin(
    request: Request,
    service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AdminPrincipal:
    """管理端鉴权：校验 JWT 并确认账号、会话仍有效。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("未登录或登录已过期")

    context = service.authenticate_access_token(credentials.credentials)
    user: AdminUser = context.user
    principal = AdminPrincipal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        session_id=context.session_id,
    )
    request.state.admin_user = principal
    set_user_id(user.id)
    return principal


def require_editor(principal: Annotated[AdminPrincipal, Depends(require_admin)]) -> AdminPrincipal:
    """写操作权限：admin 与 superadmin。"""
    if principal.role not in EDITOR_ROLES:
        raise ForbiddenError("当前角色无权执行该操作")
    return principal


def require_superadmin(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminPrincipal:
    """超级管理员权限。"""
    if principal.role != "superadmin":
        raise ForbiddenError("需要超级管理员权限")
    return principal


def require_user(authorization: Annotated[str | None, Header()] = None) -> UserPrincipal:
    """用户端鉴权：校验静态令牌（骨架实现）。"""
    expected_token = get_settings().user_api_token
    if expected_token is None or not expected_token.get_secret_value():
        raise ServiceUnavailableError("服务端未配置 USER_API_TOKEN，暂不可用")
    scheme, _, token = (authorization or "").partition(" ")
    expected = expected_token.get_secret_value()
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
        raise UnauthorizedError("身份凭证无效", headers={"WWW-Authenticate": "Bearer"})
    return UserPrincipal(subject="user")


AdminAuthDep = Annotated[AdminPrincipal, Depends(require_admin)]
EditorAuthDep = Annotated[AdminPrincipal, Depends(require_editor)]
SuperadminAuthDep = Annotated[AdminPrincipal, Depends(require_superadmin)]
UserAuthDep = Annotated[UserPrincipal, Depends(require_user)]
