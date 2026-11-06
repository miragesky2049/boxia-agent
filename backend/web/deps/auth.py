"""admin 与 user 两套权限管控依赖。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from internal.application.auth_service import AuthService
from internal.application.errors import ForbiddenError, UnauthorizedError
from internal.application.user_auth_service import UserAuthService
from internal.domain.entity.permission import CONSOLE_ACCESS
from internal.infrastructure.observability.context import set_user_id
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep


@dataclass(frozen=True)
class AdminPrincipal:
    """管理端调用者身份（来自数据库校验后的访问上下文）。"""

    user_id: UUID
    username: str
    display_name: str
    role_id: UUID | None
    role_code: str
    role_name: str
    session_id: UUID
    role_ids: tuple[UUID, ...] = ()
    permissions: frozenset[str] = frozenset()
    tenant_id: UUID | None = None
    tenant_code: str | None = None
    is_platform: bool = True

    def can(self, code: str) -> bool:
        """判断当前账号是否拥有指定功能权限。"""
        return code in self.permissions


@dataclass(frozen=True)
class UserPrincipal:
    """用户端调用者身份（最终用户 JWT）。"""

    user_id: UUID
    username: str
    display_name: str
    tenant_id: UUID
    role_id: UUID
    role_code: str
    role_name: str
    session_id: UUID
    role_ids: tuple[UUID, ...] = ()
    permissions: frozenset[str] = frozenset()
    tenant_code: str | None = None


_bearer = HTTPBearer(auto_error=False)


def require_admin(
    request: Request,
    uow: UowDep,
    context: RequestContextDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AdminPrincipal:
    """管理端鉴权：校验 JWT、账号作用域，并从数据库加载角色权限。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("未登录或登录已过期")

    access = AuthService(uow).authenticate_access_token(credentials.credentials)
    user = access.user
    if user.tenant_id != context.tenant_id:
        raise UnauthorizedError("当前账号不属于该租户，请使用正确的子域名登录")
    if access.role is None:
        raise UnauthorizedError("账号角色已失效，请联系管理员")

    # 权限每次请求实时读取，角色授权变更后无需等待令牌过期即可生效
    permissions = frozenset(uow.role_permissions.list_codes_for_roles(access.role_ids))
    if CONSOLE_ACCESS not in permissions:
        raise ForbiddenError("账号未获得管理端访问权限")

    principal = AdminPrincipal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role_id=access.role.id,
        role_code=access.role.code,
        role_name=access.role.name,
        session_id=access.session_id,
        role_ids=access.role_ids,
        permissions=permissions,
        tenant_id=user.tenant_id,
        tenant_code=context.tenant.code if context.tenant else None,
        is_platform=context.is_platform,
    )
    request.state.admin_user = principal
    set_user_id(user.id)
    return principal


def require_permission(code: str) -> Callable[..., AdminPrincipal]:
    """生成功能权限校验依赖：缺少编码对应权限时返回 403。"""

    def dependency(
        principal: Annotated[AdminPrincipal, Depends(require_admin)],
    ) -> AdminPrincipal:
        if code not in principal.permissions:
            raise ForbiddenError("当前角色无权执行该操作")
        return principal

    return dependency


def require_platform_admin(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminPrincipal:
    """产品级平台作用域校验：仅 platform 子域名可用。"""
    if not principal.is_platform:
        raise ForbiddenError("该操作仅产品级运营管理平台可用")
    return principal


def require_tenant_admin(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminPrincipal:
    """租户作用域校验：仅租户子域名可用，且拥有 app:admin 权限（0068 预置码）。"""
    if principal.is_platform:
        raise ForbiddenError("该操作仅租户管理端可用")
    if not principal.can("app:admin"):
        raise ForbiddenError("缺少应用管理权限")
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
        permissions=frozenset(uow.role_permissions.list_codes_for_roles(access.role_ids)),
        tenant_code=context.tenant.code if context.tenant else None,
    )
    request.state.user = principal
    set_user_id(user.id)
    return principal


AdminAuthDep = Annotated[AdminPrincipal, Depends(require_admin)]
PlatformAdminDep = Annotated[AdminPrincipal, Depends(require_platform_admin)]
TenantAdminDep = Annotated[AdminPrincipal, Depends(require_tenant_admin)]
UserAuthDep = Annotated[UserPrincipal, Depends(require_user)]
