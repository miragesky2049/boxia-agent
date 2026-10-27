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


async def list_tools(server_url: str) -> list[McpToolSpec]:
    """连接 MCP server 并拉取工具列表。"""
    try:
        from fastmcp import Client
    except ImportError as exc:  # pragma: no cover
        raise McpClientError(
            "未安装 fastmcp 依赖，无法调用 MCP server；请在 backend 安装 fastmcp"
        ) from exc

    logger.info("mcp list_tools server=%s", server_url)
    try:
        async with Client(server_url) as client:
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


async def call_tool(server_url: str, tool_name: str, arguments: dict[str, Any]) -> str:
    """调用指定 MCP 工具并把返回内容拼接为文本。"""
    try:
        from fastmcp import Client
    except ImportError as exc:  # pragma: no cover
        raise McpClientError("未安装 fastmcp 依赖") from exc

    logger.info(
        "mcp call_tool server=%s tool=%s args_keys=%s",
        server_url,
        tool_name,
        list(arguments.keys()),
    )
    try:
        async with Client(server_url) as client:
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
