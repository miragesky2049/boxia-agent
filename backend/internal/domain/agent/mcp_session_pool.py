"""MCP 会话级连接池（M4-b F17.4，scope=conversation 时由 agent_loop 使用）。

进程内 McpSession 复用池：key=(url+headers 指纹, conversation_id)，LRU 上限 +
idle TTL 驱逐即 close（R14 防泄漏）；server 侧会话失效（session expired/404）
透明重连并重试原调用一次（F17.4）。多 worker/负载均衡部署前提见 R13 与
docs/deployment.md：会话态不保证命中同一进程，未命中即退化为一次新握手，
不产生错误语义。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from internal.domain.agent.mcp_client import McpClientError, McpSession
from internal.domain.agent.mcp_observer import mcp_observer

logger = logging.getLogger(__name__)

# PRD F17.4 默认参数：LRU 上限 64、空闲 300s 驱逐
DEFAULT_MAX_SESSIONS = 64
DEFAULT_IDLE_TTL_SECONDS = 300.0

# 会话失效特征词（fastmcp/mcp SDK 对 server 端会话丢失的报错文案子串）
_SESSION_STALE_MARKERS = ("session expired", "session not found", "unknown session", "404")


def _session_fingerprint(
    server_url: str, headers: dict[str, str] | None
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """(url, headers) 指纹：与 agent_loop run 级去重同口径。"""
    return (server_url, tuple(sorted((headers or {}).items())))


class _PoolEntry:
    __slots__ = ("session", "last_used")

    def __init__(self, session: McpSession, now: float) -> None:
        self.session = session
        self.last_used = now


class McpSessionPool:
    """按会话维度缓存 McpSession 的进程内池；调用方经 call() 使用，不自行 close。

    session_factory/clock 可注入，便于无网络的泄漏断言单测（R14 出口条件）。
    """

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        session_factory: Callable[..., Any] = McpSession,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_sessions <= 0:
            raise ValueError(f"max_sessions 必须为正数，收到 {max_sessions}")
        if idle_ttl_seconds <= 0:
            raise ValueError(f"idle_ttl_seconds 必须为正数，收到 {idle_ttl_seconds}")
        self._max_sessions = max_sessions
        self._idle_ttl = idle_ttl_seconds
        self._session_factory = session_factory
        self._clock = clock
        self._entries: OrderedDict[
            tuple[tuple[str, tuple[tuple[str, str], ...]], str], _PoolEntry
        ] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        """当前池内会话数（含未建连的惰性对象）。"""
        return len(self._entries)

    async def call(
        self,
        conversation_id: str,
        server_url: str,
        headers: dict[str, str] | None,
        timeout_seconds: float,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """经池化会话调用工具；会话失效透明重连一次，其余错误原样抛出。"""
        key = (_session_fingerprint(server_url, headers), str(conversation_id or ""))
        session = await self._acquire(key, server_url, headers, timeout_seconds)
        try:
            result = await session.call_tool(tool_name, arguments)
        except McpClientError as exc:
            if not _is_session_stale(exc):
                # 连接已被内部关闭（如调用超时）时剔除坏对象，下次调用重建
                if not session.is_connected:
                    await self._discard(key)
                raise
            logger.info(
                "mcp pool session stale, reconnect once server=%s conv=%s err=%s",
                server_url,
                key[1],
                exc,
            )
            await self._discard(key)
            fresh = await self._acquire(key, server_url, headers, timeout_seconds)
            try:
                return await fresh.call_tool(tool_name, arguments)
            except McpClientError:
                # 重连后仍失败：坏对象不留池，避免污染后续轮次
                await self._discard(key)
                raise
        return result

    async def close_all(self) -> None:
        """清空并关闭全部会话（进程收尾/测试拆卸用）；幂等。"""
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        mcp_observer().set_pool_size(0)
        for entry in entries:
            await entry.session.close()

    async def _acquire(
        self,
        key: tuple[tuple[str, tuple[tuple[str, str], ...]], str],
        server_url: str,
        headers: dict[str, str] | None,
        timeout_seconds: float,
    ) -> Any:
        async with self._lock:
            await self._evict_expired_locked()
            entry = self._entries.get(key)
            if entry is not None:
                entry.last_used = self._clock()
                self._entries.move_to_end(key)
                mcp_observer().on_reuse(server_url)
                return entry.session
            while len(self._entries) >= self._max_sessions:
                await self._evict_lru_locked()
            session = self._session_factory(server_url, headers, timeout_seconds)
            self._entries[key] = _PoolEntry(session, self._clock())
            mcp_observer().set_pool_size(len(self._entries))
            return session

    async def _evict_expired_locked(self) -> None:
        """TTL 驱逐：调用方已持锁；过期条目移出并关闭。"""
        now = self._clock()
        stale = [
            key for key, entry in self._entries.items() if now - entry.last_used >= self._idle_ttl
        ]
        for key in stale:
            await self._discard_locked(key)
        if stale:
            logger.info("mcp pool evicted %d idle sessions", len(stale))

    async def _evict_lru_locked(self) -> None:
        """LRU 驱逐最久未用的一条（容量满时），调用方已持锁。"""
        if self._entries:
            oldest = next(iter(self._entries))
            await self._discard_locked(oldest)

    async def _discard(self, key: tuple[tuple[str, tuple[tuple[str, str], ...]], str]) -> None:
        async with self._lock:
            await self._discard_locked(key)

    async def _discard_locked(
        self, key: tuple[tuple[str, tuple[tuple[str, str], ...]], str]
    ) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        mcp_observer().set_pool_size(len(self._entries))
        # 驱逐即 close（R14）；close 幂等且内部吞错
        await entry.session.close()


def _is_session_stale(exc: McpClientError) -> bool:
    """判断错误是否为 server 侧会话失效（F17.4 透明重连的触发条件）。"""
    message = str(exc).lower()
    return any(marker in message for marker in _SESSION_STALE_MARKERS)


_pool: McpSessionPool | None = None


def get_mcp_session_pool() -> McpSessionPool:
    """进程内会话池单例（组合根与节点共用同一实例）。"""
    global _pool
    if _pool is None:
        _pool = McpSessionPool()
    return _pool
