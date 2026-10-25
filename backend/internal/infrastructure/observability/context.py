"""请求级上下文：request_id 与用户标识。"""

from contextvars import ContextVar
from uuid import UUID

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[UUID | None] = ContextVar("user_id", default=None)


def get_request_id() -> str | None:
    """当前请求 ID。"""
    return _request_id.get()


def set_request_id(value: str) -> None:
    """设置当前请求 ID。"""
    _request_id.set(value)


def get_user_id() -> UUID | None:
    """当前认证用户 ID。"""
    return _user_id.get()


def set_user_id(value: UUID | None) -> None:
    """设置当前认证用户 ID。"""
    _user_id.set(value)
