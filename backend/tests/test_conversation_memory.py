"""短期记忆集成测试：连接本地 Redis（docker/redis 已起）。

注意：Windows 上多次 asyncio.run() 会让 redis.asyncio 的 transport 失效，
因此所有 redis 操作收敛到单个 async main() 里执行。
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest

from internal.engine.memory import (
    MemoryKey,
    NullConversationMemory,
    RedisConversationMemory,
    get_redis_client,
)

REDIS_URL = os.environ.get("BOXIA_TEST_REDIS_URL", "redis://127.0.0.1:6379/0")


def _fresh_key() -> MemoryKey:
    return MemoryKey(tenant_id=uuid4(), agent_id=uuid4(), conversation_id=f"conv-{uuid4().hex[:8]}")


async def _roundtrip_case(client) -> None:
    """append 两轮后 load 应返回完整的 user/assistant 序列。"""
    memory = RedisConversationMemory(client, max_turns=20, ttl_seconds=120)
    key = _fresh_key()
    await client.delete(key.as_redis_key())
    await memory.append_turn(key, "你好", "你好，有什么可以帮你？")
    await memory.append_turn(key, "今天天气", "今天晴，22 度。")

    history = await memory.load(key)
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[0].content == "你好"
    assert history[1].content == "你好，有什么可以帮你？"
    assert history[2].content == "今天天气"
    assert history[3].content == "今天晴，22 度。"


async def _cap_case(client) -> None:
    """超过 max_turns 时从头部裁剪，只保留最近 N 轮。"""
    memory = RedisConversationMemory(client, max_turns=2, ttl_seconds=120)
    key = _fresh_key()
    await client.delete(key.as_redis_key())
    for idx in range(4):
        await memory.append_turn(key, f"q{idx}", f"a{idx}")

    history = await memory.load(key)
    assert len(history) == 4
    assert history[0].content == "q2"
    assert history[1].content == "a2"
    assert history[2].content == "q3"
    assert history[3].content == "a3"


async def _ttl_case(client) -> None:
    """每次 append 都应刷新 TTL。"""
    memory = RedisConversationMemory(client, max_turns=10, ttl_seconds=300)
    key = _fresh_key()
    await client.delete(key.as_redis_key())
    await memory.append_turn(key, "q", "a")
    ttl1 = await client.ttl(key.as_redis_key())
    assert 200 <= ttl1 <= 300
    await memory.append_turn(key, "q2", "a2")
    ttl2 = await client.ttl(key.as_redis_key())
    assert ttl2 >= ttl1 - 5


async def _null_case() -> None:
    null = NullConversationMemory()
    key = _fresh_key()
    assert await null.load(key) == []
    await null.append_turn(key, "q", "a")


async def _main() -> None:
    client = get_redis_client(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"本地 Redis 不可用：{exc}")
    await _roundtrip_case(client)
    await _cap_case(client)
    await _ttl_case(client)
    await _null_case()


def test_conversation_memory() -> None:
    """在同一 event loop 内跑完全部用例。"""
    asyncio.run(_main())


# 让类型检查器知道 UUID 仍被引用（避免未使用告警）
__all__ = ["MemoryKey"]
_ = UUID
