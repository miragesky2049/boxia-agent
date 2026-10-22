"""请求级租户上下文：按二级域名解析租户，并隔离产品级/租户级作用域。

解析规则（生产）：
- ``adminsystem.xxx.com`` → 产品级平台（跨租户）；
- ``<tenant>.xxx.com`` → 对应租户；
- 根域名 ``xxx.com`` → 可配置默认租户，未配置则拒绝访问。

开发/测试环境额外支持 ``X-Tenant-Code`` 请求头：``platform`` 表示产品级，
其他值表示租户编码，便于本地以 localhost 调试。
"""

from typing import Annotated

from fastapi import Depends, Request

from internal.application.errors import ForbiddenError, NotFoundError
from internal.domain.entity.request_context import (
    PLATFORM_SCOPE,
    TENANT_SCOPE,
    RequestContext,
)
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.postgres_tenant_repository import (
    PostgresTenantRepository,
)

TENANT_HEADER = "X-Tenant-Code"
PLATFORM_HEADER_VALUE = "platform"
# 本地开发地址不参与子域名解析，避免配置 ROOT_DOMAIN 后 localhost 调试被拒绝。
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "testserver"}

__all__ = [
    "PLATFORM_HEADER_VALUE",
    "PLATFORM_SCOPE",
    "TENANT_HEADER",
    "TENANT_SCOPE",
    "RequestContext",
    "RequestContextDep",
    "get_request_context",
]


def _host_without_port(request: Request) -> str:
    host = request.headers.get("host") or request.url.hostname or ""
    host = host.strip().lower()
    if host.startswith("["):  # IPv6 字面量
        return host.split("]")[0] + "]"
    return host.split(":")[0].rstrip(".")


def _load_tenant(code: str) -> Tenant:
    """按租户编码加载租户并校验启用状态。"""
    session = get_session_factory()()
    try:
        tenant = PostgresTenantRepository(session).get_by_code(code)
    finally:
        session.close()
    if tenant is None:
        raise NotFoundError(f"租户不存在：{code}")
    if not tenant.is_active:
        raise ForbiddenError("租户已停用，请联系平台管理员")
    return tenant


def _resolve_from_header(request: Request) -> RequestContext | None:
    settings = get_settings()
    if not settings.tenant_header_enabled:
        return None
    code = (request.headers.get(TENANT_HEADER) or "").strip().lower()
    if not code:
        return None
    if code == PLATFORM_HEADER_VALUE:
        return RequestContext(scope=PLATFORM_SCOPE, tenant=None, host=_host_without_port(request))
    return RequestContext(
        scope=TENANT_SCOPE, tenant=_load_tenant(code), host=_host_without_port(request)
    )


def _resolve_from_host(request: Request) -> RequestContext | None:
    settings = get_settings()
    root = settings.normalized_root_domain
    if not root:
        return None

    host = _host_without_port(request)
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        return None
    platform_host = f"{settings.platform_admin_subdomain.strip().lower()}.{root}"
    if host == platform_host:
        return RequestContext(scope=PLATFORM_SCOPE, tenant=None, host=host)

    suffix = f".{root}"
    if host.endswith(suffix):
        label = host[: -len(suffix)]
        if not label or "." in label:
            raise NotFoundError("租户域名格式不正确，仅支持一级子域名")
        return RequestContext(scope=TENANT_SCOPE, tenant=_load_tenant(label), host=host)

    if host == root:
        if settings.default_tenant_code:
            return RequestContext(
                scope=TENANT_SCOPE,
                tenant=_load_tenant(settings.default_tenant_code.lower()),
                host=host,
            )
        raise NotFoundError("请通过租户子域名访问")

    raise NotFoundError("无法识别的访问域名")


def get_request_context(request: Request) -> RequestContext:
    """解析当前请求的租户上下文；开发态请求头优先于域名。"""
    context = _resolve_from_header(request) or _resolve_from_host(request)
    if context is not None:
        return context
    # 未配置根域名且未携带租户头的开发环境，默认进入产品级平台。
    return RequestContext(scope=PLATFORM_SCOPE, tenant=None, host=_host_without_port(request))


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]
