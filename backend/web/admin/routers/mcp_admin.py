"""管理端 MCP server 接口（0074 PRD F6.1/F6.4）。

POST /api/v1/admin/mcp-servers/discover：按 URL 拉取 MCP server 工具清单，
供智能体配置页勾选；勾选结果由前端快照进画布 config.mcpServers。
SSRF 校验与 30s 结果缓存在应用服务 McpDiscoveryService 内完成。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from internal.application.apps.mcp_discovery_service import mcp_discovery_service
from internal.domain.agent.mcp_client import McpClientError
from internal.domain.errors import ServiceUnavailableError

router = APIRouter(prefix="/mcp-servers", tags=["mcp-admin"])

MAX_HEADERS = 16


class McpDiscoverPayload(BaseModel):
    """MCP server 发现请求体。"""

    server_url: str = Field(alias="serverUrl", min_length=1, max_length=2048)
    headers: dict[str, str] | None = Field(default=None, max_length=MAX_HEADERS)

    model_config = {"populate_by_name": True}


@router.post("/discover")
async def discover_mcp_tools(payload: McpDiscoverPayload) -> dict[str, Any]:
    """连接 MCP server 返回工具清单（名称/描述/入参 schema）供勾选。

    server 地址非法由 SSRF 校验抛 ValidationError（400）；server 不可达或
    协议错误抛 McpClientError，这里转 ServiceUnavailableError（503），
    错误信息携带 server URL 便于管理员排查配置。
    """
    try:
        return await mcp_discovery_service.discover(payload.server_url, payload.headers)
    except McpClientError as exc:
        raise ServiceUnavailableError(f"MCP server 不可用：{exc}") from exc
