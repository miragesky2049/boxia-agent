"""应用层统一异常，Web 层据此转换为 HTTP 响应。"""


class AppError(Exception):
    """业务异常基类。"""

    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class UnauthorizedError(AppError):
    """未登录、令牌无效或已过期。"""

    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    """身份有效但无权限（如账号被禁用）。"""

    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    """资源不存在。"""

    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    """资源冲突，如名称重复。"""

    status_code = 409
    code = "CONFLICT"


class ValidationError(AppError):
    """业务规则校验失败。"""

    status_code = 422
    code = "VALIDATION_ERROR"


class RateLimitError(AppError):
    """请求过于频繁或账号被临时锁定。"""

    status_code = 429
    code = "RATE_LIMITED"


class AccountLockedError(RateLimitError):
    """登录失败次数超限，账号临时锁定。"""

    code = "ACCOUNT_LOCKED"


class ServiceUnavailableError(AppError):
    """依赖组件不可用。"""

    status_code = 503
    code = "SERVICE_UNAVAILABLE"
