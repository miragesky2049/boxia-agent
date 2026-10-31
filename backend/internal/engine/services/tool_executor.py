"""把 ToolGateway + ToolEntity 体系适配成画布节点期望的 `tool_executor` service。

画布节点（LLM ReAct 循环 / API 插件节点）通过 `ctx.services.get("tool_executor")` 拿执行器，
调用签名：`observation: str = await tool_executor(name, args)`。

本 service 负责：
1. 按 name 从 ToolRepository 查 ToolEntity（可见范围 = 当前租户 + 平台授权）
2. 用 `build_tools` 构造运行期 Tool 实例（HttpTool / McpTool / EchoTool）
3. 绑定 AgentRunContext（tenant_id / user_id / agent_id / conversation_id / run_id）
4. 调 `tool.invoke(args, ctx)`，任何异常转成文本 observation 回灌 LLM，不抛给主循环
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from internal.engine.context import AgentRunContext
from internal.engine.tool_gateway import ToolExecutionError
from internal.engine.tools import EchoTool, Tool, build_tools
from internal.infrastructure.repository.postgres_resource_repository import (
    PostgresToolRepository,
)

logger = logging.getLogger(__name__)

# 单次 run 内允许加载的最大工具数：防误配置导致内存爆炸
MAX_LOADED_TOOLS = 200


class ToolExecutorService:
    """画布节点专用的工具执行器；可被 await 调用。

    构造时绑定一次 run 的身份信息，节点 handler 只需传 (name, args)。
    工具列表 lazy 加载：第一次调用时按可见范围拉全量 enabled 工具并建 name 索引。
    """

    def __init__(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        application_id: UUID,
        run_id: UUID | str,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._application_id = application_id
        self._run_id = str(run_id)
        self._tools_cache: dict[str, Tool] | None = None

    async def __call__(self, name: str, args: dict[str, Any]) -> str:
        """按工具名执行；返回 observation 文本（异常也转文本）。"""
        await self._ensure_loaded()
        assert self._tools_cache is not None

        tool = self._tools_cache.get(name)
        if tool is None:
            available = "、".join(sorted(self._tools_cache.keys())) or "无"
            return f"[error] 工具未注册: {name}。可用工具：{available}"

        context = AgentRunContext(
            agent_id=self._application_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            conversation_id=self._run_id,
            run_id=self._run_id,
        )

        try:
            return await tool.invoke(args or {}, context)
        except ToolExecutionError as exc:
            return f"[error] {exc.message}"
        except Exception as exc:  # noqa: BLE001 - 工具异常不中断 LLM 主循环
            logger.exception("工具执行异常: tool=%s", name)
            return f"[error] {name}: {exc}"

    async def _ensure_loaded(self) -> None:
        """lazy 加载租户可见的 enabled 工具列表；同一 run 内只查一次库。"""
        if self._tools_cache is not None:
            return

        repo = PostgresToolRepository(
            self._session,
            tenant_id=self._tenant_id,
            apply_role_filter=False,
        )
        entities, _total = repo.list_page(
            page=1,
            page_size=MAX_LOADED_TOOLS,
            keyword=None,
            is_enabled=True,
        )
        tools = build_tools(entities)
        # 内置 echo 工具默认注入，方便本地冒烟测试
        cache: dict[str, Tool] = {t.name: t for t in tools}
        cache.setdefault("echo", EchoTool())
        self._tools_cache = cache
