"""通用键值缓存抽象：供 graph / 配置等热路径使用。

与 AuthCache 区别：
- AuthCache 只存 dict（json 序列化），面向鉴权场景
- KvCache 面向任意可 json 序列化的对象，支持批量 mget / mset / 失效
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KvCache(ABC):
    """通用 KV 缓存接口。"""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def publish(self, channel: str, message: str) -> None:
        """发布失效广播（多节点缓存同步）。"""

    @abstractmethod
    async def subscribe(self, channel: str) -> Any:
        """订阅失效广播（返回上下文管理器或消息迭代器）。"""
