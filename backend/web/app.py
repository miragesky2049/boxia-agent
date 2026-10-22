"""FastAPI 应用装配入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from internal.infrastructure.config.settings import Settings, get_settings
from internal.infrastructure.middleware.access_log import AccessLogMiddleware
from internal.infrastructure.middleware.audit import AuditMiddleware
from internal.infrastructure.middleware.request_id import RequestIdMiddleware
from internal.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from internal.infrastructure.middleware.trace_middleware import install_trace
from internal.infrastructure.model.database import dispose_engine
from internal.infrastructure.observability.logging import setup_logging
from internal.infrastructure.observability.metrics import setup_metrics
from web.api_v1 import build_api_router
from web.errors import install_exception_handlers
from web.health import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """应用工厂：配置、日志、可观测性、异常处理与路由一次装配。"""
    settings = settings or get_settings()
    setup_logging(settings)

    docs_enabled = settings.effective_docs_enabled
    application = FastAPI(
        title="Boxia Agent",
        description="Boxia Agent 管理端与用户端 API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

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
    api_router = build_api_router()
    application.include_router(api_router, prefix="/api/v1")
    if settings.legacy_api_enabled:
        application.include_router(api_router, prefix="/api", include_in_schema=False)

    @application.get("/", include_in_schema=False)
    def health_banner() -> dict[str, str]:
        """根路径返回服务标识，便于探活。"""
        return {"service": settings.app_name, "version": settings.app_version}

    logger.info("application created env=%s", settings.app_env)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)
