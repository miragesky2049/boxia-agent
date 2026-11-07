"""工作流即工具服务（0074 PRD F7，20261107）。

把已发布 workflow 应用暴露为智能体可调用工具：
- describe：按 start 节点"启动参数"生成工具 schema（domain/canvas/workflow_tool 纯函数）；
- invoke：同进程经 RunnerFactory 装配子 GraphRuntime 执行，不落独立租户配额，
  子 run 以 parent_run_id 关联父 run（run 表列由 0075 迁移添加）；
- 递归防护：调用链 workflow_chain 随子 run 入参下传，链内出现重复应用 ID 即环、
  链长达到 MAX_WORKFLOW_TOOL_DEPTH 即拒绝（PRD F7.2 / 风险 R5）。

DDD 定位：domain 的 agent_loop 节点只按 duck-typing 调本服务的两个方法
（ctx.services["workflow_tool"]），装配由组合根 web/deps/graph.py 完成。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.ports import RunnerFactory
from internal.domain.canvas.workflow_tool import build_start_input_schema

logger = logging.getLogger(__name__)

# agent→workflow→agent 链最大深度（PRD F7.2）：超限拒绝，防成本/递归失控
MAX_WORKFLOW_TOOL_DEPTH = 3

# 子 run 线程前缀：每次工具调用独立 thread，避免与父会话 checkpoint 互相污染
_CHILD_THREAD_PREFIX = "wf-tool"


class WorkflowToolService:
    """单个父 run 维度的工作流工具端口：describe / invoke。"""

    def __init__(
        self,
        app_service: ApplicationService,
        runner_factory: RunnerFactory,
        uow: Any,
        context: Any,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        parent_run_id: UUID,
        actor_username: str | None = None,
        conversation_id: UUID | None = None,
    ) -> None:
        self._app_service = app_service
        self._runner_factory = runner_factory
        self._uow = uow
        self._context = context
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._parent_run_id = parent_run_id
        self._actor_username = actor_username
        self._conversation_id = conversation_id

    async def describe(
        self,
        application_id: str,
        chain: list[str],
    ) -> dict[str, Any] | None:
        """返回 {name, description, parameters}；应用不存在/不可见/非 workflow 返回 None。

        None 表示该挂载项当前不可用，节点侧跳过合成工具（配置保留，恢复后可用）。
        """
        resolved = await self._resolve_target(application_id, chain, spec_only=True)
        if resolved is None:
            return None
        card, graph = resolved
        return {
            "name": str(card.get("name") or ""),
            "description": str(card.get("description") or ""),
            "parameters": build_start_input_schema(graph),
        }

    async def invoke(
        self,
        application_id: str,
        arguments: dict[str, Any],
        chain: list[str],
    ) -> str:
        """执行目标 workflow 并返回文本 observation。

        目标不可用/环/超深抛 RuntimeError，由 ReAct 内核转 [error] observation
        回灌模型自纠，不中断对话（与知识库工具失败语义一致）。
        """
        resolved = await self._resolve_target(application_id, chain, spec_only=False)
        if resolved is None:
            raise RuntimeError(f"工作流工具不可用：应用 {application_id} 不存在、不可见或非工作流类型")
        card, _graph = resolved

        child_thread_id = (
            f"{_CHILD_THREAD_PREFIX}:{self._parent_run_id}:{application_id}"
        )
        runner = await self._runner_factory(
            self._app_service,
            self._uow,
            self._context,
            tenant_id=self._tenant_id,
            application_id=UUID(application_id),
            thread_id=child_thread_id,
            current_user_id=self._user_id,
            actor_username=self._actor_username,
            conversation_id=self._conversation_id,
            parent_run_id=self._parent_run_id,
        )
        # 入参即 start 变量；workflow_chain 下传给孙代 agent 做环/深度判定
        start_inputs = dict(arguments or {})
        start_inputs["workflow_chain"] = [*chain, application_id]
        output = await runner.invoke(start_inputs)
        return self._observation_text(card, output)

    async def _resolve_target(
        self,
        application_id: str,
        chain: list[str],
        *,
        spec_only: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """鉴权 + 类型 + 环/深度校验，返回 (卡片, 运行时 graph)。

        spec_only=True 用于 describe：只跳过不可用项，不做环/深度硬拒绝
        （工具清单可先展示，执行时再兜底）。invoke 路径做完整防护。
        """
        try:
            app_id = UUID(str(application_id))
        except (TypeError, ValueError):
            logger.warning("工作流工具 applicationId 非法: %r", application_id)
            return None
        if self._user_id is None:
            logger.warning("工作流工具缺少用户身份，跳过 application=%s", app_id)
            return None
        card = self._app_service.get_visible_app_for_user(
            app_id, self._tenant_id, self._user_id
        )
        if card is None or card.get("flow_type") != "workflow":
            return None
        if not spec_only:
            normalized = str(app_id)
            if normalized in chain:
                raise RuntimeError(
                    f"检测到工作流工具循环调用：「{card.get('name')}」已在调用链 {chain} 中"
                )
            if len(chain) >= MAX_WORKFLOW_TOOL_DEPTH:
                raise RuntimeError(
                    f"工作流工具嵌套深度超过上限 {MAX_WORKFLOW_TOOL_DEPTH}，请拆平流程或减少挂载"
                )
        graph = await self._app_service.get_runtime_graph(app_id, self._tenant_id)
        return card, graph

    @staticmethod
    def _observation_text(card: dict[str, Any], output: Any) -> str:
        """把 workflow 终态输出转成工具 observation 文本。"""
        if isinstance(output, str):
            return output or "（工作流无输出）"
        if output:
            return json.dumps(output, ensure_ascii=False)
        return f"工作流「{card.get('name')}」执行完成，无文本输出"
