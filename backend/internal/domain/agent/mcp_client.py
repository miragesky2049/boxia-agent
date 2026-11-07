"""MCP 客户端：调用外部 MCP server 的 list_tools / call_tool。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpToolSpec:
    """从 MCP server 拉到的工具描述。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


class McpClientError(Exception):
    """MCP 调用失败。"""


def _make_client(server_url: str, headers: dict[str, str] | None):
    """构造 fastmcp Client；带自定义请求头时走 StreamableHttpTransport。

    0074 PRD F6：MCP server 多需 API Key 等请求头，fastmcp 的裸 URL 形态不支持，
    显式构造 transport 传入 headers。依赖缺失在此统一抛 McpClientError。
    """
    try:
        from fastmcp import Client
    except ImportError as exc:  # pragma: no cover
        raise McpClientError(
            "未安装 fastmcp 依赖，无法调用 MCP server；请在 backend 安装 fastmcp"
        ) from exc
    if not headers:
        return Client(server_url)
    from fastmcp.client.transports import StreamableHttpTransport

    return Client(StreamableHttpTransport(url=server_url, headers=dict(headers)))


async def list_tools(server_url: str, headers: dict[str, str] | None = None) -> list[McpToolSpec]:
    """连接 MCP server 并拉取工具列表。"""
    logger.info("mcp list_tools server=%s", server_url)
    client = _make_client(server_url, headers)
    try:
        async with client:
            tools = await client.list_tools()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp list_tools failed server=%s err=%s", server_url, exc)
        raise McpClientError(f"无法连接 MCP server {server_url}: {exc}") from exc

    return [
        McpToolSpec(
            name=tool.name,
            description=tool.description or "",
            input_schema=dict(tool.input_schema or {}),
        )
        for tool in tools
    ]


async def call_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> str:
    """调用指定 MCP 工具并把返回内容拼接为文本。"""
    logger.info(
        "mcp call_tool server=%s tool=%s args_keys=%s",
        server_url,
        tool_name,
        list(arguments.keys()),
    )
    client = _make_client(server_url, headers)
    try:
        async with client:
            result = await client.call_tool(tool_name, arguments)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp call_tool failed server=%s tool=%s err=%s", server_url, tool_name, exc)
        raise McpClientError(f"调用 MCP 工具 {tool_name} 失败: {exc}") from exc

    # fastmcp CallResult.content 是 list[TextContent|...]]，取 text 拼接
    parts: list[str] = []
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else ""
