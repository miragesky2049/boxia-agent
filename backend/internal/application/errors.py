"""应用层统一异常，Web 层据此转换为 HTTP 响应。

异常类统一定义已下沉到 ``internal.domain.errors``，本模块保留为兼容入口。
"""

from internal.domain.errors import (
    AccountLockedError,
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ResourceDeprecatedError,
    ResourceNotApprovedError,
    ResourceNotEntitledError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)

__all__ = [
    "AccountLockedError",
    "AppError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ResourceDeprecatedError",
    "ResourceNotApprovedError",
    "ResourceNotEntitledError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
