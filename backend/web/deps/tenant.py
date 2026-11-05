"""请求级租户上下文：按域名解析租户，请求头仅作为本地调试逃生口。

解析优先级（所有环境一致，域名优先）：
1. ``platform.<ROOT_DOMAIN>`` → 产品级平台（跨租户）；
2. ``<tenant>.<ROOT_DOMAIN>`` → 对应租户；
3. 根域名 ``<ROOT_DOMAIN>`` → 可配置默认租户，未配置则拒绝访问；
4. local 环境的回环/本机主机（``localhost``、``127.0.0.1``、局域网 IP 等）
   在开启 ``ALLOW_TENANT_HEADER`` 时可用 ``X-Tenant-Code`` 临时切换，``platform``
   表示产品级；
5. local 环境兜底为默认租户或产品级平台；其余环境无法识别的 Host 一律 404，
   绝不静默回退产品级平台。
"""

import ipaddress
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request

from internal.application.errors import ForbiddenError, NotFoundError
from internal.domain.entity.request_context import (
    PLATFORM_SCOPE,
    TENANT_SCOPE,
    RequestContext,
)
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.config.settings import Settings, get_settings
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.postgres_tenant_repository import (
    PostgresTenantRepository,
)

TENANT_HEADER = "X-Tenant-Code"
PLATFORM_HEADER_VALUE = "platform"
# 本机调试入口：这些 Host 不参与子域名解析，仅用于 header 覆盖或兜底
_BOOTSTRAP_HOSTS = {"localhost", "testserver"}
# 与租户编码、平台子域名保持一致的一级标签格式
_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

__all__ = [
    "PLATFORM_HEADER_VALUE",
    "PLATFORM_SCOPE",
    "TENANT_HEADER",
    "TENANT_SCOPE",
    "RequestContext",
    "RequestContextDep",
    "get_request_context",
    "is_bootstrap_host",
    "tenant_switch_mode",
]


def _host_without_port(request: Request) -> str:
    """从 Host 头或请求 URL 提取小写、无端口、无尾点的主机名。"""
    raw = (request.headers.get("host") or "").strip()
    try:
        hostname = urlsplit(f"//{raw}").hostname if raw else request.url.hostname
    except ValueError:
        hostname = ""
    return (hostname or "").lower().rstrip(".")


def is_bootstrap_host(host: str) -> bool:
    """是否为本地调试入口（回环地址、任意 IP 字面量或 testserver）。"""
    if host in _BOOTSTRAP_HOSTS:
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def tenant_switch_mode(
    settings: Settings, context: RequestContext
) -> Literal["none", "header", "host"]:
    """前端作用域切换方式：none=仅域名，header=本地请求头，host=本地子域名跳转。"""
    if not settings.is_local:
        return "none"
    return "header" if is_bootstrap_host(context.host) else "host"


def _load_tenant(code: str) -> Tenant:
    """按租户编码加载租户并校验启用状态。"""
    if not _LABEL_PATTERN.match(code):
        raise NotFoundError("租户编码格式不正确")
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


def _resolve_from_header(request: Request, settings: Settings) -> RequestContext | None:
    """本地调试请求头覆盖；仅 local 且显式开启时生效。"""
    if not settings.is_local or not settings.allow_tenant_header:
        return None
    code = (request.headers.get(TENANT_HEADER) or "").strip().lower()
    if not code:
        return None
    host = _host_without_port(request)
    if code == PLATFORM_HEADER_VALUE:
        return RequestContext(PLATFORM_SCOPE, None, host, resolution="header")
    return RequestContext(TENANT_SCOPE, _load_tenant(code), host, resolution="header")


def _resolve_from_host(request: Request) -> RequestContext | None:
    """按域名解析作用域；返回 None 表示交给本地 header/默认兜底。"""
    settings = get_settings()
    host = _host_without_port(request)

    # 本机调试入口不使用子域名解析，交给请求头或默认作用域
    if settings.is_local and is_bootstrap_host(host):
        return None

    root = settings.normalized_root_domain
    if not root:
        raise NotFoundError("未配置租户根域名，无法识别访问域名")

    if host == settings.platform_admin_host:
        return RequestContext(PLATFORM_SCOPE, None, host, resolution="host")

    suffix = f".{root}"
    if host.endswith(suffix):
        label = host[: -len(suffix)]
        if not label or "." in label or not _LABEL_PATTERN.match(label):
            raise NotFoundError("租户域名格式不正确，仅支持一级子域名")
        return RequestContext(TENANT_SCOPE, _load_tenant(label), host, resolution="host")

    if host == root:
        if settings.default_tenant_code:
            return RequestContext(
                TENANT_SCOPE,
                _load_tenant(settings.default_tenant_code.lower()),
                host,
                resolution="host",
            )
        if settings.is_local:
            return None
        raise NotFoundError("请通过租户子域名访问")

    raise NotFoundError("无法识别的访问域名")


def get_request_context(request: Request) -> RequestContext:
    """解析当前请求的租户上下文：域名优先，本地回环主机才允许请求头覆盖。"""
    settings = get_settings()
    context = _resolve_from_host(request)
    if context is not None:
        return context

    header_context = _resolve_from_header(request, settings)
    if header_context is not None:
        return header_context

    if not settings.is_local:
        raise NotFoundError("无法识别的访问域名")

    host = _host_without_port(request)
    if settings.default_tenant_code:
        return RequestContext(
            TENANT_SCOPE,
            _load_tenant(settings.default_tenant_code.lower()),
            host,
            resolution="default",
        )
    return RequestContext(PLATFORM_SCOPE, None, host, resolution="default")


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]
