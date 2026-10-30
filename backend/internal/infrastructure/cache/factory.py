"""Redis 客户端工厂：lru_cache 单例。"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis

from internal.domain.cache.base import KvCache
from internal.infrastructure.cache.redis_kv_cache import InMemoryKvCache, RedisKvCache
from internal.infrastructure.config.settings import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=False)


@lru_cache(maxsize=1)
def get_kv_cache() -> KvCache:
    """应用主进程使用的 KV 缓存。

    测试环境可通过 set_kv_cache_override 替换为内存实现。
    """
    return RedisKvCache(get_redis_client())


def set_kv_cache_override(cache: KvCache) -> None:
    """测试注入内存缓存。"""
    get_kv_cache.cache_clear()
    get_kv_cache.__wrapped__ = lambda: cache  # type: ignore[attr-defined]
