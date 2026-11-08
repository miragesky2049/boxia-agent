"""M4-b T-b5：MCP 会话级连接池（F17.4 / R14）。

无网络单测：以 fake session_factory + 注入 clock 断言复用、隔离、TTL/LRU
驱逐即 close、会话失效透明重连一次、坏对象剔除与观测水位上报。
"""

from __future__ import annotations

import asyncio

import pytest

from internal.domain.agent.mcp_client import McpClientError
from internal.domain.agent.mcp_observer import (
    McpCallRecord,
    configure_mcp_observer,
    mcp_observer,
)
from internal.domain.agent.mcp_session_pool import McpSessionPool


class _FakeSession:
    """记录调用与关闭的 fake McpSession；行为由脚本注入。"""

    def __init__(self, url: str, headers=None, timeout_seconds: float = 30.0) -> None:
        self.server_url = url
        self.timeout_seconds = timeout_seconds
        self.calls: list[tuple[str, dict]] = []
        self.closed = 0
        self.connected = True
        self._results: list[object] = []

    @property
    def is_connected(self) -> bool:
        return self.connected

    def enqueue(self, *results: object) -> None:
        self._results.extend(results)

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        self.calls.append((tool_name, arguments))
        if self._results:
            result = self._results.pop(0)
            if isinstance(result, Exception):
                raise result
            return str(result)
        return f"{tool_name}:{len(self.calls)}"

    async def close(self) -> None:
        self.closed += 1
        self.connected = False


class _Factory:
    def __init__(self) -> None:
        self.created: list[_FakeSession] = []

    def __call__(self, url: str, headers=None, timeout_seconds: float = 30.0) -> _FakeSession:
        session = _FakeSession(url, headers, timeout_seconds)
        self.created.append(session)
        return session


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingObserver:
    def __init__(self) -> None:
        self.handshakes: list[str] = []
        self.reuses: list[str] = []
        self.pool_sizes: list[int] = []

    def on_handshake(self, server: str) -> None:
        self.handshakes.append(server)

    def on_reuse(self, server: str) -> None:
        self.reuses.append(server)

    def observe_call(self, record: McpCallRecord) -> None:
        return None

    def set_pool_size(self, size: int) -> None:
        self.pool_sizes.append(size)


@pytest.fixture()
def observer() -> _RecordingObserver:
    """临时替换全局 MCP 观测端口，用例结束恢复原实现（可能是 Prometheus 装配）。"""
    previous = mcp_observer()
    recording = _RecordingObserver()
    configure_mcp_observer(recording)
    yield recording
    configure_mcp_observer(previous)


def _make_pool(
    factory: _Factory,
    clock: _Clock,
    *,
    max_sessions: int = 64,
    idle_ttl: float = 300.0,
) -> McpSessionPool:
    return McpSessionPool(
        max_sessions=max_sessions,
        idle_ttl_seconds=idle_ttl,
        session_factory=factory,
        clock=clock,
    )


def _call(
    pool: McpSessionPool, conv: str = "c1", tool: str = "echo", url: str = "http://s/mcp"
) -> str:
    return asyncio.run(pool.call(conv, url, {"X-K": "1"}, 30.0, tool, {"a": 1}))


def test_same_key_reuses_single_session(observer) -> None:
    """同 (指纹, conversation_id) 多次调用只建一个会话；第二次计一次复用。"""
    factory = _Factory()
    pool = _make_pool(factory, _Clock())
    assert _call(pool) == "echo:1"
    # 同一会话对象：fake 以调用序号回显，"add:2" 本身即复用证据
    assert _call(pool, tool="add") == "add:2"
    assert len(factory.created) == 1
    assert observer.reuses == ["http://s/mcp"]
    assert observer.pool_sizes == [1]


def test_isolated_per_conversation_and_fingerprint(observer) -> None:
    """conversation_id 或 headers 指纹不同 → 独立会话，互不串用（F17.4 key 语义）。"""
    factory = _Factory()
    pool = _make_pool(factory, _Clock())
    _call(pool, conv="c1")
    _call(pool, conv="c2")
    asyncio.run(pool.call("c1", "http://s/mcp", {"X-K": "2"}, 30.0, "echo", {}))
    assert len(factory.created) == 3
    assert all(len(s.calls) == 1 for s in factory.created)


def test_idle_ttl_evicts_and_closes() -> None:
    """空闲超过 TTL：下次获取前驱逐并 close（R14 驱逐即关，不留死连接）。"""
    factory = _Factory()
    clock = _Clock()
    pool = _make_pool(factory, clock, idle_ttl=100.0)
    _call(pool)
    clock.advance(101.0)
    _call(pool)
    assert factory.created[0].closed == 1
    assert factory.created[1].closed == 0
    assert pool.size == 1


def test_lru_cap_evicts_oldest() -> None:
    """池满驱逐最久未用的一条并 close，容量不越过 max。"""
    factory = _Factory()
    clock = _Clock()
    pool = _make_pool(factory, clock, max_sessions=2)
    _call(pool, conv="c1")
    clock.advance(1.0)
    _call(pool, conv="c2")
    clock.advance(1.0)
    _call(pool, conv="c3")
    assert factory.created[0].closed == 1
    assert factory.created[1].closed == 0
    assert pool.size == 2


def test_stale_session_reconnects_and_retries_once() -> None:
    """server 侧会话失效：丢弃旧会话、重建一次并重放原调用（F17.4 透明重连）。"""
    factory = _Factory()
    first = _FakeSession("http://s/mcp")
    first.enqueue(McpClientError("Session not found: 404 from server"))

    def _factory(url: str, headers=None, timeout_seconds: float = 30.0) -> _FakeSession:
        session = first if not factory.created else _FakeSession(url, headers, timeout_seconds)
        factory.created.append(session)
        return session

    pool = McpSessionPool(session_factory=_factory, clock=_Clock())
    assert asyncio.run(pool.call("c1", "http://s/mcp", None, 30.0, "echo", {})) == "echo:1"
    assert len(factory.created) == 2
    assert first.closed == 1
    assert first.calls and factory.created[1].calls


def test_non_stale_error_no_retry() -> None:
    """非会话失效错误不重连不重放，原样上抛；坏连接（is_connected=False）剔除。"""
    first = _FakeSession("http://s/mcp")
    first.enqueue(McpClientError("调用 MCP 工具 echo 超时（30.0s）"))
    first.connected = False
    created: list[_FakeSession] = []

    def _factory(url: str, headers=None, timeout_seconds: float = 30.0) -> _FakeSession:
        session = first if not created else _FakeSession(url, headers, timeout_seconds)
        created.append(session)
        return session

    pool = McpSessionPool(session_factory=_factory, clock=_Clock())
    with pytest.raises(McpClientError, match="超时"):
        asyncio.run(pool.call("c1", "http://s/mcp", None, 30.0, "echo", {}))
    assert first.closed == 1
    assert len(created) == 1
    assert pool.size == 0


def test_close_all_closes_every_session(observer) -> None:
    """close_all 清空并逐个关闭，水位归零；幂等可重复调用。"""
    factory = _Factory()
    pool = _make_pool(factory, _Clock())
    _call(pool, conv="c1")
    _call(pool, conv="c2")
    asyncio.run(pool.close_all())
    asyncio.run(pool.close_all())
    assert all(s.closed == 1 for s in factory.created)
    assert pool.size == 0
    assert observer.pool_sizes[-1] == 0


def test_rejected_invalid_params() -> None:
    """max_sessions / idle_ttl 非正数在构造期即拒绝（契约式校验）。"""
    with pytest.raises(ValueError):
        McpSessionPool(max_sessions=0)
    with pytest.raises(ValueError):
        McpSessionPool(idle_ttl_seconds=0.0)
