"""MCP server 自动发现服务（0074 PRD F6.1/F6.3）。

职责：管理端配置面"填 URL → 拉工具清单 → 勾选快照"的服务端支撑。
- SSRF 校验复用 ToolGateway 同口径的 validate_outbound_url（F6.4）；
- 结果按 (url, headers) 做 30s TTL 缓存（对齐租户工具目录缓存口径，防
  配置页反复点开 discover 打爆外部 server）；
- server 不可达抛 McpClientError 转 503 语义由调用方（路由）决定。

发现结果只用于人工勾选，快照写入画布 config.mcpServers.enabledTools 后
运行时不再依赖 server 可用性（F6.1），因此本服务不参与运行链路。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from internal.domain.agent.mcp_client import list_tools
from internal.domain.security.ssrf_guard import validate_outbound_url

# discover 结果缓存 TTL（秒）：与 tool_executor 目录缓存同口径
DISCOVER_CACHE_TTL_SECONDS = 30.0

# 缓存上限：防恶意/失控的 URL 组合把进程内存吃满，超限整体清空（缓存非事实源）
DISCOVER_CACHE_MAX_ENTRIES = 128


class McpDiscoveryService:
    """MCP server 工具清单自动发现（带 30s TTL 进程内缓存）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[
            tuple[str, tuple[tuple[str, str], ...]], tuple[float, list[dict[str, Any]]]
        ] = {}

    async def discover(
        self,
        server_url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """连接 MCP server 拉取工具清单；返回 {serverUrl, tools, fromCache}。

        serverUrl 非法（scheme/host/网段）抛 ValidationError；server 不可达
        抛 McpClientError，由路由层转成对用户可读的错误响应。
        """
        url = validate_outbound_url((server_url or "").strip())
        key = (url, tuple(sorted((headers or {}).items())))

        cached = self._get_cached(key)
        if cached is not None:
            return {"serverUrl": url, "tools": cached, "fromCache": True}

        specs = await list_tools(url, headers=headers)
        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            }
            for spec in specs
        ]
        self._store(key, tools)
        return {"serverUrl": url, "tools": tools, "fromCache": False}

    def _get_cached(self, key: tuple) -> list[dict[str, Any]] | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry[0] <= time.monotonic():
                self._cache.pop(key, None)
                return None
            return [dict(tool) for tool in entry[1]]

    def _store(self, key: tuple, tools: list[dict[str, Any]]) -> None:
        with self._lock:
            if len(self._cache) >= DISCOVER_CACHE_MAX_ENTRIES:
                self._cache.clear()
            self._cache[key] = (time.monotonic() + DISCOVER_CACHE_TTL_SECONDS, list(tools))


def clear_discover_cache() -> None:
    """清空发现缓存（测试与运维手动失效用）。"""
    _service = mcp_discovery_service
    with _service._lock:  # noqa: SLF001 - 模块级单例的受控失效入口
        _service._cache.clear()


# 进程级单例：缓存跨请求共享（与 ToolExecutorService 的目录缓存同形态）
mcp_discovery_service = McpDiscoveryService()
