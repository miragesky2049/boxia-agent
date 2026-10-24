"""admin 与 user 两套权限管控依赖。"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from internal.application.auth_service import AuthService
from internal.application.errors import ForbiddenError, UnauthorizedError
from internal.application.user_auth_service import UserAuthService
from internal.domain.entity.access import SYSTEM_ROLE_PERMISSIONS
from internal.domain.entity.admin_user import EDITOR_ROLES
from internal.infrastructure.observability.context import set_user_id
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep


@dataclass(frozen=True)
class AdminPrincipal:
    """管理端调用者身份（来自数据库校验后的访问上下文）。"""

    user_id: int
    username: str
    display_name: str
    role: str
    session_id: UUID
    role_id: int | None = None
    role_ids: tuple[int, ...] = ()
    system_role: str = "admin"
    permissions: frozenset[str] = frozenset()
    tenant_id: int | None = None
    tenant_code: str | None = None
    is_platform: bool = True


@dataclass(frozen=True)
class UserPrincipal:
    """用户端调用者身份（最终用户 JWT）。"""

    user_id: int
    username: str
    display_name: str
    tenant_id: int
    role_id: int
    role_code: str
    role_name: str
    session_id: UUID
    role_ids: tuple[int, ...] = ()
    tenant_code: str | None = None


_bearer = HTTPBearer(auto_error=False)


def require_admin(
    request: Request,
    uow: UowDep,
    context: RequestContextDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AdminPrincipal:
    """管理端鉴权：校验 JWT，并确认账号属于当前子域名对应的作用域。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("未登录或登录已过期")

    access = AuthService(uow).authenticate_access_token(credentials.credentials)
    user = access.user
    if user.tenant_id != context.tenant_id:
        raise UnauthorizedError("当前账号不属于该租户，请使用正确的子域名登录")

    system_role = access.role.system_role if access.role is not None else user.role
    principal = AdminPrincipal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=system_role,
        session_id=access.session_id,
        role_id=access.role.id if access.role is not None else user.role_id,
        role_ids=access.role_ids,
        system_role=system_role,
        permissions=frozenset(SYSTEM_ROLE_PERMISSIONS.get(system_role, ("read",))),
        tenant_id=user.tenant_id,
        tenant_code=context.tenant.code if context.tenant else None,
        is_platform=context.is_platform,
    )
    request.state.admin_user = principal
    set_user_id(user.id)
    return principal


def require_editor(principal: Annotated[AdminPrincipal, Depends(require_admin)]) -> AdminPrincipal:
    """写操作权限：admin 与 superadmin。"""
    if principal.system_role not in EDITOR_ROLES:
        raise ForbiddenError("当前角色无权执行该操作")
    return principal


def require_superadmin(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminPrincipal:
    """超级管理员权限（产品级或租户级超级管理员）。"""
    if principal.system_role != "superadmin":
        raise ForbiddenError("需要超级管理员权限")
    return principal


def require_platform_superadmin(
    principal: Annotated[AdminPrincipal, Depends(require_superadmin)],
) -> AdminPrincipal:
    """产品级平台超级管理员权限：仅 adminsystem 子域名可用。"""
    if not principal.is_platform:
        raise ForbiddenError("该操作仅产品级运营管理平台可用")
    return principal


def require_user(
    request: Request,
    uow: UowDep,
    context: RequestContextDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> UserPrincipal:
    """用户端鉴权：校验最终用户 JWT，并要求请求来自租户子域名。"""
    if context.is_platform or context.tenant is None:
        raise ForbiddenError("用户端仅支持通过租户子域名访问")
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("未登录或登录已过期")

    access = UserAuthService(uow).authenticate_access_token(credentials.credentials)
    user = access.user
    if user.tenant_id != context.tenant_id:
        raise UnauthorizedError("当前账号不属于该租户，请使用正确的子域名登录")

    principal = UserPrincipal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        role_id=access.role.id,
        role_code=access.role.code,
        role_name=access.role.name,
        session_id=access.session_id,
        role_ids=access.role_ids,
        tenant_code=context.tenant.code if context.tenant else None,
    )
    request.state.user = principal
    set_user_id(user.id)
    return principal


AdminAuthDep = Annotated[AdminPrincipal, Depends(require_admin)]
EditorAuthDep = Annotated[AdminPrincipal, Depends(require_editor)]
SuperadminAuthDep = Annotated[AdminPrincipal, Depends(require_superadmin)]
PlatformSuperadminDep = Annotated[AdminPrincipal, Depends(require_platform_superadmin)]
UserAuthDep = Annotated[UserPrincipal, Depends(require_user)]
