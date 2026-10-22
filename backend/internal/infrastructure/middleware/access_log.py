"""访问日志中间件：记录方法、路径、状态码与耗时。"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("boxia.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    """统一访问日志，替代 uvicorn 默认 access log。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if request.url.path not in {"/health/live", "/health/ready", "/metrics"}:
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else "-",
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
        return response
