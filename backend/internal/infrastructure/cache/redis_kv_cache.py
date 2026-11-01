"""Redis KvCache 实现：基于 redis.asyncio。"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from internal.domain.cache.base import KvCache

logger = logging.getLogger(__name__)


class RedisKvCache(KvCache):
    """Redis KV 缓存：所有 value 按 JSON 序列化。"""

    def __init__(self, client: aioredis.Redis) -> None:
        self._r = client

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        await self._r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def publish(self, channel: str, message: str) -> None:
        await self._r.publish(channel, message)

    async def subscribe(self, channel: str) -> Any:
        pubsub = self._r.pubsub()
        await pubsub.subscribe(channel)
        return pubsub


class InMemoryKvCache(KvCache):
    """测试用：纯内存实现，无广播。"""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.store.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def publish(self, channel: str, message: str) -> None:
        pass

    async def subscribe(self, channel: str) -> Any:
        return None
