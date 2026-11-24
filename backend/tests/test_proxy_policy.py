"""环回代理策略与 MCP 本地直连回归测试（20261124）。"""

from __future__ import annotations

import asyncio

from internal.domain.agent.mcp_client import McpSession
from internal.domain.security.proxy_policy import httpx_trust_env, is_loopback_url


def test_is_loopback_url_cases() -> None:
    """环回判定：127.x/localhost/::1 为环回，其余（含私网）保持默认代理行为。"""
    assert is_loopback_url("http://127.0.0.1:61946/mcp")
    assert is_loopback_url("http://localhost:8000/api")
    assert is_loopback_url("http://[::1]:1234/mcp")
    assert not is_loopback_url("https://mcp.example.com/sse")
    assert not is_loopback_url("http://10.0.0.5:9000/mcp")
    assert not is_loopback_url("不是URL")


def test_httpx_trust_env_mapping() -> None:
    """trust_env 映射：环回 False（直连），外部 True（沿用环境代理）。"""
    assert httpx_trust_env("http://127.0.0.1:9/mcp") is False
    assert httpx_trust_env("https://api.external.com") is True


def test_mcp_session_connects_with_broken_system_proxy(in_process_mcp_server, monkeypatch) -> None:
    """回归：系统代理指向死端口时，环回 MCP server 仍必须可连通。

    复现开发机开代理后 test_mcp_session 成片失败的场景：monkeypatch 注入
    HTTP_PROXY/HTTPS_PROXY 指向必然拒连的本地端口；修复后 _make_client 的
    httpx 工厂对环回目标 trust_env=False，代理配置被忽略，调用正常。
    """
    server_url = in_process_mcp_server.url
    dead_proxy = "http://127.0.0.1:1"
    monkeypatch.setenv("HTTP_PROXY", dead_proxy)
    monkeypatch.setenv("HTTPS_PROXY", dead_proxy)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")

    async def scenario() -> str:
        session = McpSession(server_url)
        await session.connect()
        try:
            return await session.call_tool("echo", {"text": "hi"})
        finally:
            await session.close()

    result = asyncio.run(scenario())
    assert result == "echo:hi"
