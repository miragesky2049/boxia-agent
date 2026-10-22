"""Prometheus 业务指标与 HTTP 指标装配。"""

import time

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.pool import QueuePool
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from internal.infrastructure.model.database import get_engine

LOGIN_SUCCESS = Counter("boxia_login_success_total", "登录成功次数")
LOGIN_FAILURE = Counter("boxia_login_failure_total", "登录失败次数", ["reason"])
REFRESH_FAILURE = Counter("boxia_refresh_failure_total", "刷新令牌失败次数", ["reason"])
AUDIT_WRITE_FAILURE = Counter("boxia_audit_write_failure_total", "审计写入失败次数")

HTTP_REQUESTS = Counter(
    "boxia_http_requests_total",
    "HTTP 请求数",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "boxia_http_request_duration_seconds",
    "HTTP 请求耗时",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def _pool_metric(getter: str) -> int:
    """仅对队列连接池采集指标（NullPool 等无此能力）。"""
    pool = get_engine().pool
    if not isinstance(pool, QueuePool):
        return 0
    return int(getattr(pool, getter)())


_DB_POOL_CHECKED_OUT = Gauge("boxia_db_pool_checked_out", "数据库连接池已借出连接数")
_DB_POOL_CHECKED_OUT.set_function(lambda: _pool_metric("checkedout"))
_DB_POOL_SIZE = Gauge("boxia_db_pool_size", "数据库连接池当前连接数")
_DB_POOL_SIZE.set_function(lambda: _pool_metric("size"))

_SKIP_PREFIXES = ("/health", "/metrics")


class MetricsMiddleware:
    """记录 HTTP 请求量与耗时；路由使用模板路径避免标签爆炸。"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        started = time.perf_counter()
        status = 500

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            HTTP_REQUESTS.labels(method=method, route=route_path, status=str(status)).inc()
            HTTP_DURATION.labels(method=method, route=route_path).observe(
                time.perf_counter() - started
            )


def setup_metrics(app: FastAPI) -> None:
    """安装 HTTP 指标中间件并暴露 /metrics。"""
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    def metrics(_: Request) -> Response:
        """Prometheus 文本格式指标。"""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
