"""短期记忆：基于 Redis 的多轮会话历史缓存。

每个 (tenant, agent, conversation) 维度维护一个 JSON list：
- 只保留 user / assistant 文本消息（tool 调用轨迹不落库，审计日志单独记）
- 每次 append 后刷新 TTL（滑动过期）
- 超过 max_turns 时从头部裁剪
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis

from internal.engine.messages import AssistantMessage, ChatMessage, UserMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryKey:
    """会话记忆的主键。"""

    tenant_id: UUID | None
    agent_id: UUID
    conversation_id: str

    def as_redis_key(self) -> str:
        """生成 Redis key；租户级 / 产品级用 - 占位区分。"""
        tenant = str(self.tenant_id) if self.tenant_id else "platform"
        return f"boxia:memory:{tenant}:{self.agent_id}:{self.conversation_id}"


class ConversationMemory(ABC):
    """短期记忆抽象：便于测试注入 / 未来替换实现。"""

    @abstractmethod
    async def load(self, key: MemoryKey) -> list[ChatMessage]:
        """读取会话历史；无历史返回空列表。"""

    @abstractmethod
    async def append_turn(
        self,
        key: MemoryKey,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """把一轮 user + assistant 消息追加到历史；超出上限时从头部裁剪。"""


class RedisConversationMemory(ConversationMemory):
    """Redis 实现的短期记忆。"""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        max_turns: int = 20,
        ttl_seconds: int = 1800,
    ) -> None:
        self._client = client
        self._max_messages = max_turns * 2
        self._ttl = ttl_seconds

    async def load(self, key: MemoryKey) -> list[ChatMessage]:
        """读取会话历史并反序列化为内部消息模型。"""
        raw = await self._client.get(key.as_redis_key())
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("memory decode failed key=%s", key.as_redis_key())
            return []
        return self._coerce(items)

    async def append_turn(
        self,
        key: MemoryKey,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """追加一轮消息并刷新 TTL。"""
        redis_key = key.as_redis_key()
        existing = await self._client.get(redis_key)
        items: list[dict[str, Any]] = []
        if existing:
            try:
                items = json.loads(existing)
            except (ValueError, TypeError):
                items = []
        items.append({"role": "user", "content": user_message})
        items.append({"role": "assistant", "content": assistant_message})
        if len(items) > self._max_messages:
            items = items[-self._max_messages :]
        await self._client.set(redis_key, json.dumps(items, ensure_ascii=False), ex=self._ttl)

    @staticmethod
    def _coerce(items: list[dict[str, Any]]) -> list[ChatMessage]:
        """把 dict 列表转换为内部消息模型；忽略无法识别的角色。"""
        messages: list[ChatMessage] = []
        for item in items:
            role = item.get("role")
            content = str(item.get("content") or "")
            if role == "user":
                messages.append(UserMessage(content=content))
            elif role == "assistant":
                messages.append(AssistantMessage(content=content))
        return messages


class NullConversationMemory(ConversationMemory):
    """空实现：无 Redis 或显式禁用时使用，每次都当首轮处理。"""

    async def load(self, key: MemoryKey) -> list[ChatMessage]:
        return []

    async def append_turn(
        self,
        key: MemoryKey,
        user_message: str,
        assistant_message: str,
    ) -> None:
        return


# 进程级单例客户端：按 redis_url 缓存，避免每请求新建连接池
_client_cache: dict[str, aioredis.Redis] = {}


def get_redis_client(redis_url: str) -> aioredis.Redis:
    """按 URL 复用 Redis 客户端（带连接池）。"""
    if redis_url not in _client_cache:
        _client_cache[redis_url] = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=False,
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
        )
    return _client_cache[redis_url]


def build_conversation_memory(redis_url: str, *, max_turns: int, ttl_seconds: int) -> ConversationMemory:
    """按 settings 构造短期记忆实现；URL 为空串时降级为 Null 实现。"""
    if not redis_url:
        return NullConversationMemory()
    return RedisConversationMemory(
        get_redis_client(redis_url),
        max_turns=max_turns,
        ttl_seconds=ttl_seconds,
    )
