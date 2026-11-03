"""领域层统一异常，应用层 / Web 层据此转换为 HTTP 响应。"""


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


class SelfReviewForbiddenError(ForbiddenError):
    """资源创建人不能审核自己创建的资源（职责分离）。"""

    code = "SELF_REVIEW_FORBIDDEN"


class NotFoundError(AppError):
    """资源不存在。"""

    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    """资源冲突，如名称重复。"""

    status_code = 409
    code = "CONFLICT"


class VersionConflictError(ConflictError):
    """同幂等键的请求仍在执行中（P3-8），调用方应稍后重试而非重复提交。"""

    code = "VERSION_CONFLICT"


class ValidationError(AppError):
    """业务规则校验失败。"""

    status_code = 422
    code = "VALIDATION_ERROR"


class ResourceNotEntitledError(ValidationError):
    """角色授权目标资源未对当前租户开通权益。"""

    code = "RESOURCE_NOT_ENTITLED"


class ResourceNotApprovedError(ValidationError):
    """角色授权目标资源尚未通过审核。"""

    code = "RESOURCE_NOT_APPROVED"


class ResourceDeprecatedError(ValidationError):
    """角色授权目标资源已弃用，不可新授权。"""

    code = "RESOURCE_DEPRECATED"


class QuotaExceededError(ValidationError):
    """权益配额超限（P3-10），调用方应引导购买方扩容或释放占用。"""

    code = "QUOTA_EXCEEDED"


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
