"""MCP 工具同步接口：从外部 MCP server 拉取工具并注册到 boxia-agent。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from web.admin.schemas.resource import ToolOut
from web.deps.services import McpSyncServiceDep

router = APIRouter(prefix="/mcp", tags=["admin-mcp"])


class McpSyncRequest(BaseModel):
    """从 MCP server 同步工具的请求体。"""

    server_url: str = Field(
        ...,
        pattern=r"^https?://",
        max_length=500,
        description="MCP server 地址，如 http://127.0.0.1:8090/mcp",
    )
    agent_id: UUID | None = Field(
        None, description="可选：把同步下来的工具直接归属到该智能体"
    )


class McpSyncResponse(BaseModel):
    """同步结果。"""

    server_url: str
    synced_count: int
    tools: list[ToolOut]


@router.post("/tools/sync", response_model=McpSyncResponse)
async def sync_tools(
    payload: McpSyncRequest,
    service: McpSyncServiceDep,
) -> McpSyncResponse:
    """从指定 MCP server 拉取工具列表并 upsert 到 tools 表。

    同一作用域内同名工具已存在时按配置更新（type=mcp），否则新建。
    """
    tools = await service.sync_from_server(
        server_url=payload.server_url,
        agent_id=payload.agent_id,
    )
    return McpSyncResponse(
        server_url=payload.server_url,
        synced_count=len(tools),
        tools=[ToolOut.model_validate(t) for t in tools],
    )
