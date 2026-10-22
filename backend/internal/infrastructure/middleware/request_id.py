"""Request ID 中间件：生成或沿用调用方传入的追踪标识。"""

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from internal.infrastructure.observability.context import set_request_id

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
HEADER_NAME = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个请求建立 request_id 上下文并回写响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(HEADER_NAME, "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        set_request_id(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER_NAME] = request_id
        return response
