"""FastAPI 应用工厂：admin 与 user 站点共用基础设施，路由各自独立装配。"""

import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from internal.engine.llm import shutdown_llm_clients
from internal.infrastructure.bootstrap import ensure_platform_admin
from internal.infrastructure.config.settings import Settings, get_settings
from internal.infrastructure.middleware.access_log import AccessLogMiddleware
from internal.infrastructure.middleware.audit import AuditMiddleware
from internal.infrastructure.middleware.request_id import RequestIdMiddleware
from internal.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from internal.infrastructure.middleware.trace_middleware import install_trace
from internal.infrastructure.model.database import dispose_engine
from internal.infrastructure.observability.logging import setup_logging
from internal.infrastructure.observability.metrics import setup_metrics
from web.api_v1 import build_admin_api_router, build_user_api_router
from web.errors import install_exception_handlers
from web.health import router as health_router

logger = logging.getLogger(__name__)

SiteName = Literal["admin", "user"]

_SITE_META: dict[SiteName, tuple[str, str]] = {
    "admin": ("Boxia Agent Admin", "Agent 运营管理端 API"),
    "user": ("Boxia Agent User", "Agent Chat 用户端 API"),
}


@asynccontextmanager
async def lifespan(application: FastAPI):
    site = getattr(application.state, "site", None)
    settings = get_settings()
    if site == "admin":
        try:
            ensure_platform_admin(settings)
        except Exception:
            logger.exception("平台管理员自动初始化失败")
    yield
    await shutdown_llm_clients()
    dispose_engine()


def create_app(site: SiteName, settings: Settings | None = None) -> FastAPI:
    """应用工厂：按站点装配共享基础设施，仅挂载该站点自己的 API 路由。"""
    settings = settings or get_settings()
    setup_logging(settings)

    title, description = _SITE_META[site]
    docs_enabled = settings.effective_docs_enabled
    application = FastAPI(
        title=title,
        description=description,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.state.site = site

    if settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Request-ID",
                "X-Tenant-Code",
            ],
            expose_headers=["X-Request-ID", "traceparent"],
        )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(AuditMiddleware)
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(RequestIdMiddleware)

    install_trace(application, settings)
    install_exception_handlers(application)
    setup_metrics(application)

    application.include_router(health_router)
    api_router = build_admin_api_router() if site == "admin" else build_user_api_router()
    application.include_router(api_router, prefix="/api/v1")
    if settings.legacy_api_enabled:
        application.include_router(api_router, prefix="/api", include_in_schema=False)

    @application.get("/", include_in_schema=False)
    def health_banner() -> dict[str, str]:
        """根路径返回服务标识，便于探活。"""
        return {"service": settings.app_name, "site": site, "version": settings.app_version}

    logger.info("application created site=%s env=%s", site, settings.app_env)
    return application
