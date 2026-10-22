"""安全响应头中间件。"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_AUTH_PATH_PREFIXES = ("/api/v1/admin/auth", "/api/admin/auth")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """补齐 API 安全响应头，认证接口禁止缓存。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith(_AUTH_PATH_PREFIXES):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
