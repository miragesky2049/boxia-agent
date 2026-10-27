"""MCP 工具同步用例：从外部 MCP server 拉取工具列表，upsert 到 boxia-agent tools 表。"""

from __future__ import annotations

import logging
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.resource import Tool
from internal.domain.repository.protocols import UnitOfWork
from internal.engine.mcp_client import McpClientError, list_tools

logger = logging.getLogger(__name__)


class McpSyncService:
    """MCP 工具同步：把外部 server 的工具注册为 boxia-agent 内的 tool.type='mcp' 记录。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext) -> None:
        self._uow = uow
        self._context = context

    async def sync_from_server(
        self,
        *,
        server_url: str,
        agent_id: UUID | None = None,
    ) -> list[Tool]:
        """拉取 MCP server 全部工具并 upsert 到 tools 表。

        - 同一作用域内同名 tool 已存在时按配置更新；否则新建
        - 若指定 agent_id，工具会归属到该智能体
        """
        if not server_url.startswith(("http://", "https://")):
            raise ValidationError("server_url 必须以 http:// 或 https:// 开头")

        if agent_id is not None:
            agent = self._uow.agents.get(agent_id)
            if agent is None:
                raise NotFoundError("智能体不存在或当前作用域不可见")

        try:
            specs = await list_tools(server_url)
        except McpClientError as exc:
            raise ValidationError(str(exc)) from exc

        if not specs:
            return []

        synced: list[Tool] = []
        for spec in specs:
            existing = self._uow.tools.get_by_name(spec.name)
            config = {
                "server_url": server_url,
                "tool_name": spec.name,
                "input_schema": spec.input_schema,
            }
            values = {
                "name": spec.name,
                "description": spec.description,
                "type": "mcp",
                "config": config,
                "is_enabled": True,
                "agent_id": agent_id,
            }
            if existing is not None:
                updated = self._uow.tools.update(existing.id, values)
                if updated is not None:
                    synced.append(updated)
            else:
                synced.append(self._uow.tools.create(values))

        self._uow.commit()
        logger.info(
            "mcp sync done server=%s agent=%s count=%d",
            server_url,
            agent_id,
            len(synced),
        )
        return synced
