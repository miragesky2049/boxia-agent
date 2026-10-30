"""鉴权缓存抽象：AuthService 不直接依赖 Redis 客户端。

具体实现由 infrastructure 层提供（如 RedisAuthCache / InMemoryAuthCache 用于测试）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AuthCache(ABC):
    """鉴权缓存接口。key 形如 `auth:{tenant_id}:{app_id}`。"""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """读缓存，未命中返回 None。"""

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """写缓存，带 TTL。"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """失效缓存（授权变更时调用）。"""
