"""0074 PRD F6.4：管理端 MCP discover 端点层回归（鉴权、SSRF 422、server 不可达 503 兜底）。

服务层缓存/透传细节已在 test_mcp_discovery_service.py 覆盖，本文件只锁 HTTP 契约。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from internal.application.apps import mcp_discovery_service as discovery_module
from internal.domain.agent.mcp_client import McpClientError, McpToolSpec

DISCOVER_URL = "/api/v1/admin/mcp-servers/discover"
# RFC1918 白名单允许且免 DNS 解析（离线 CI 安全）
SAFE_URL = "http://10.255.255.1:9000/mcp"


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_discover_requires_login(client: TestClient) -> None:
    resp = client.post(DISCOVER_URL, json={"serverUrl": SAFE_URL})
    assert resp.status_code == 401


def test_discover_rejects_loopback_url(client: TestClient) -> None:
    headers = _platform_headers(client)
    resp = client.post(
        DISCOVER_URL, json={"serverUrl": "http://127.0.0.1:9000/mcp"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_discover_requires_server_url(client: TestClient) -> None:
    headers = _platform_headers(client)
    resp = client.post(DISCOVER_URL, json={"headers": {}}, headers=headers)
    assert resp.status_code == 422


def test_discover_server_unavailable_maps_503(client: TestClient, monkeypatch) -> None:
    async def _fail(url: str, headers: dict[str, str] | None = None) -> list[Any]:
        raise McpClientError(f"无法连接 MCP server {url}")

    monkeypatch.setattr(discovery_module, "list_tools", _fail)
    headers = _platform_headers(client)
    resp = client.post(
        DISCOVER_URL,
        json={"serverUrl": SAFE_URL, "headers": {"Authorization": "Bearer x"}},
        headers=headers,
    )
    assert resp.status_code == 503
    assert "MCP server 不可用" in resp.json()["detail"]


def test_discover_success_response_shape(client: TestClient, monkeypatch) -> None:
    async def _ok(url: str, headers: dict[str, str] | None = None) -> list[Any]:
        return [
            McpToolSpec(name="add", description="做加法", input_schema={"type": "object", "properties": {}})
        ]

    monkeypatch.setattr(discovery_module, "list_tools", _ok)
    discovery_module.mcp_discovery_service._cache.clear()  # noqa: SLF001 - 隔离缓存键
    headers = _platform_headers(client)
    resp = client.post(DISCOVER_URL, json={"serverUrl": SAFE_URL}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["serverUrl"] == SAFE_URL
    assert body["fromCache"] is False
    assert body["tools"][0]["name"] == "add"
    assert "inputSchema" in body["tools"][0]
