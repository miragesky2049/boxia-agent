"""McpSession 本体测试（M4-b F17.7：进程内 fastmcp server，真协议栈）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from internal.domain.agent import mcp_client as mcp_client_module
from internal.domain.agent.mcp_client import (
    DEFAULT_TIMEOUT_SECONDS,
    McpClientError,
    McpSession,
    McpToolSpec,
)

_TIMEOUT_MARK = "超时"


def test_connect_call_close_roundtrip(in_process_mcp_server):
    """显式生命周期：connect→call→close 全链路可用。"""

    async def scenario() -> tuple[str, bool, bool]:
        session = McpSession(in_process_mcp_server.url)
        await session.connect()
        connected = session.is_connected
        out = await session.call_tool("echo", {"text": "hi"})
        await session.close()
        return out, connected, session.is_connected

    out, connected, after_close = asyncio.run(scenario())
    assert out == "echo:hi"
    assert connected
    assert not after_close


def test_reuse_single_handshake_for_multiple_calls(in_process_mcp_server):
    """核心收益：一次 connect 后多次 call_tool 只产生 1 次握手（F17.2 验收）。"""
    in_process_mcp_server.reset()

    async def scenario() -> list[str]:
        session = McpSession(in_process_mcp_server.url)
        await session.connect()
        outs = [await session.call_tool("echo", {"text": str(i)}) for i in range(3)]
        await session.close()
        return outs

    outs = asyncio.run(scenario())
    assert outs == ["echo:0", "echo:1", "echo:2"]
    assert in_process_mcp_server.handshakes == 1
    assert in_process_mcp_server.call_count == 3


def test_lazy_connect_on_first_call(in_process_mcp_server):
    """未显式 connect 直接 call：自动建连且不额外多握手。"""
    in_process_mcp_server.reset()

    async def scenario() -> str:
        session = McpSession(in_process_mcp_server.url)
        out = await session.call_tool("echo", {"text": "lazy"})
        await session.close()
        return out

    assert asyncio.run(scenario()) == "echo:lazy"
    assert in_process_mcp_server.handshakes == 1


def test_list_tools_returns_specs(in_process_mcp_server):
    """会话上 list_tools 返回 McpToolSpec（含 input_schema）。"""

    async def scenario() -> list[McpToolSpec]:
        async with McpSession(in_process_mcp_server.url) as session:
            return await session.list_tools()

    specs = asyncio.run(scenario())
    names = {spec.name for spec in specs}
    assert {"echo", "add", "fail", "slow"} <= names
    echo_spec = next(spec for spec in specs if spec.name == "echo")
    assert echo_spec.input_schema.get("type") == "object"
    assert "text" in json.dumps(echo_spec.input_schema)


def test_is_error_prefixed(in_process_mcp_server):
    """工具执行失败（isError）返回 [error] 前缀文本而非抛错（F17.3④）。"""

    async def scenario() -> str:
        async with McpSession(in_process_mcp_server.url) as session:
            return await session.call_tool("fail", {})

    out = asyncio.run(scenario())
    assert out.startswith("[error] ")
    assert "boom-xyz" in out


def test_structured_content_preferred(in_process_mcp_server):
    """structuredContent 存在时优先 JSON 序列化返回（F17.3⑤）。"""

    async def scenario() -> str:
        async with McpSession(in_process_mcp_server.url) as session:
            return await session.call_tool("add", {"a": 2, "b": 3})

    assert json.loads(asyncio.run(scenario())) == {"sum": 5}


def test_headers_persist_across_calls(in_process_mcp_server):
    """自定义 headers 在复用连接的每次请求均送达（T-b0 spike 结论回归）。"""

    async def scenario() -> list[str]:
        session = McpSession(in_process_mcp_server.url, headers={"X-Mcp-Test": "hdr-1"})
        await session.connect()
        outs = [await session.call_tool("show_header", {}) for _ in range(2)]
        await session.close()
        return outs

    assert asyncio.run(scenario()) == ["hdr-1", "hdr-1"]


def test_call_timeout_raises_and_closes_session(in_process_mcp_server):
    """条目级超时：wait_for 触发后抛 McpClientError 并关闭不可信连接（F17.3②）。"""

    async def scenario() -> tuple[str, bool]:
        session = McpSession(in_process_mcp_server.url, timeout_seconds=0.2)
        await session.connect()
        with pytest.raises(McpClientError) as exc_info:
            await session.call_tool("slow", {"seconds": 5})
        return str(exc_info.value), session.is_connected

    message, still_connected = asyncio.run(scenario())
    assert _TIMEOUT_MARK in message
    assert not still_connected


def test_close_idempotent(in_process_mcp_server):
    """close 幂等：重复关闭与未连接关闭均不抛（T-b0 spike 结论回归）。"""

    async def scenario() -> None:
        session = McpSession(in_process_mcp_server.url)
        await session.connect()
        await session.close()
        await session.close()
        await McpSession(in_process_mcp_server.url).close()

    asyncio.run(scenario())


def test_reconnect_after_close(in_process_mcp_server):
    """close 后可重新 connect：产生新握手且调用可用（审批挂起恢复路径基础）。"""
    in_process_mcp_server.reset()

    async def scenario() -> str:
        session = McpSession(in_process_mcp_server.url)
        await session.connect()
        await session.call_tool("echo", {"text": "first"})
        await session.close()
        await session.connect()
        out = await session.call_tool("echo", {"text": "second"})
        await session.close()
        return out

    assert asyncio.run(scenario()) == "echo:second"
    assert in_process_mcp_server.handshakes == 2


def test_connect_failure_retries_once(in_process_mcp_server, monkeypatch):
    """握手失败重试 1 次后放弃，抛 McpClientError（F17.3③）。"""

    attempts = {"n": 0}
    original = mcp_client_module._make_client

    def counting_make_client(server_url, headers):
        attempts["n"] += 1
        return original("http://127.0.0.1:1/mcp", headers)  # 不可达端口

    monkeypatch.setattr(mcp_client_module, "_make_client", counting_make_client)

    async def scenario() -> None:
        await McpSession(in_process_mcp_server.url).connect()

    with pytest.raises(McpClientError) as exc_info:
        asyncio.run(scenario())
    assert attempts["n"] == 2
    assert "已重试 1 次" in str(exc_info.value)


def test_facade_call_tool_compat(in_process_mcp_server):
    """兼容门面 call_tool 行为保持：短连接一次调用。"""
    in_process_mcp_server.reset()

    out = asyncio.run(mcp_client_module.call_tool(in_process_mcp_server.url, "echo", {"text": "f"}))
    assert out == "echo:f"
    assert in_process_mcp_server.handshakes == 1


def test_facade_list_tools_compat(in_process_mcp_server):
    """兼容门面 list_tools 行为保持：discovery 服务不动。"""

    specs = asyncio.run(mcp_client_module.list_tools(in_process_mcp_server.url))
    assert all(isinstance(spec, McpToolSpec) for spec in specs)
    assert "echo" in {spec.name for spec in specs}


def test_default_timeout_constant():
    """F17.3② 口径：默认超时 30s。"""
    assert DEFAULT_TIMEOUT_SECONDS == 30.0


def test_connect_notifies_handshake_observer(in_process_mcp_server):
    """F17.6 钩子：每次成功建连上报一次握手；复用既有连接不重复上报。"""
    from internal.domain.agent.mcp_observer import configure_mcp_observer, mcp_observer

    previous = mcp_observer()
    handshakes: list[str] = []

    class _Recording:
        def on_handshake(self, server: str) -> None:
            handshakes.append(server)

        def on_reuse(self, server: str) -> None:
            pass

        def observe_call(self, record) -> None:  # noqa: ANN001 - 测试桩
            pass

        def set_pool_size(self, size: int) -> None:
            pass

    async def scenario() -> None:
        configure_mcp_observer(_Recording())
        try:
            session = McpSession(in_process_mcp_server.url)
            await session.connect()
            await session.call_tool("echo", {"text": "a"})
            await session.call_tool("echo", {"text": "b"})
            await session.close()
        finally:
            configure_mcp_observer(previous)

    asyncio.run(scenario())
    assert handshakes == [in_process_mcp_server.url]
