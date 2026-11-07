"""0074 PRD F6.1/F6.3：MCP discover 服务单测（SSRF / TTL 缓存 / 错误透传）。"""

from __future__ import annotations

import asyncio

import pytest

from internal.application.apps import mcp_discovery_service as module
from internal.application.apps.mcp_discovery_service import McpDiscoveryService
from internal.domain.agent.mcp_client import McpClientError, McpToolSpec
from internal.domain.errors import ValidationError


def _discover(svc: McpDiscoveryService, url: str, headers=None) -> dict:
    return asyncio.run(svc.discover(url, headers))


def test_discover_rejects_loopback_before_connecting(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(module, "list_tools", lambda *a, **k: calls.append(a[0]))

    svc = McpDiscoveryService()
    with pytest.raises(ValidationError):
        _discover(svc, "http://127.0.0.1:9000/mcp")
    assert calls == []


def test_discover_rejects_non_http_scheme(monkeypatch) -> None:
    monkeypatch.setattr(module, "list_tools", lambda *a, **k: None)
    svc = McpDiscoveryService()
    with pytest.raises(ValidationError):
        _discover(svc, "file:///etc/passwd")


def test_discover_result_shape_and_cache_hit(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_list_tools(server_url: str, headers=None):
        calls.append(server_url)
        return [McpToolSpec(name="geocode", description="地址转坐标", input_schema={"type": "object"})]

    monkeypatch.setattr(module, "list_tools", _fake_list_tools)
    svc = McpDiscoveryService()

    first = _discover(svc, "http://10.255.255.1:9000/mcp")
    assert first["fromCache"] is False
    assert first["tools"] == [
        {"name": "geocode", "description": "地址转坐标", "inputSchema": {"type": "object"}}
    ]

    second = _discover(svc, "http://10.255.255.1:9000/mcp")
    assert second["fromCache"] is True
    assert len(calls) == 1
    # 缓存返回深拷贝，调用方改动不污染缓存
    second["tools"][0]["name"] = "mutated"
    third = _discover(svc, "http://10.255.255.1:9000/mcp")
    assert third["tools"][0]["name"] == "geocode"


def test_discover_cache_key_includes_headers(monkeypatch) -> None:
    calls: list[tuple] = []

    async def _fake_list_tools(server_url: str, headers=None):
        calls.append((server_url, tuple(sorted((headers or {}).items()))))
        return [McpToolSpec(name="t", description="", input_schema={})]

    monkeypatch.setattr(module, "list_tools", _fake_list_tools)
    svc = McpDiscoveryService()
    _discover(svc, "http://10.255.255.1:9000/mcp", {"X-KEY": "a"})
    _discover(svc, "http://10.255.255.1:9000/mcp", {"X-KEY": "b"})
    _discover(svc, "http://10.255.255.1:9000/mcp", {"X-KEY": "a"})
    assert len(calls) == 2  # 同 url 不同 headers 分开缓存；相同 headers 命中


def test_discover_connect_error_propagates(monkeypatch) -> None:
    async def _boom(server_url: str, headers=None):
        raise McpClientError(f"无法连接 MCP server {server_url}: refused")

    monkeypatch.setattr(module, "list_tools", _boom)
    svc = McpDiscoveryService()
    with pytest.raises(McpClientError):
        _discover(svc, "http://10.255.255.1:9000/mcp")
    # 失败不落缓存：下次仍会真实重试
    with pytest.raises(McpClientError):
        _discover(svc, "http://10.255.255.1:9000/mcp")
