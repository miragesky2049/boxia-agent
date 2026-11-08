"""智能体即工具服务（M4 PRD F14.2，20261107）。

把已发布的 agent 应用暴露为智能体可委派工具（M4-c 委派形态）：
- describe：合成工具名 `agent_{slug}`（或配置 toolName 覆盖）、固定 `{question: string}`
  入参 schema——子代理是对话体，输入就是一句话，不给 start schema；
- invoke：同进程经 RunnerFactory 装配子 GraphRuntime 执行，新 run 行以 parent_run_id
  关联父 run（RunsPage children 链路可见，F14.4），thread=`{parent}:sub:{app_id}`
  与父会话 checkpoint 隔离（R22 同口径防叠套）；
- 递归防护：与 workflow 即工具共用祖先链与预算（call_chain 共享，深度≤3 + 链路去环，
  R15），agent→workflow→agent 混合链同样受限；
- 目标门槛：同租户用户可见 + flow_type=agent + 已发布（F14.1），不可用在 describe
  返回 None（跳过合成）、invoke 抛 RuntimeError（转 [error] observation 回灌模型自纠）。

C8 子 run 不投记忆抽取：抽取只由 ChatService 主会话提交后投递（F16.3），
子 run 走 runner.invoke 不经该路径，天然不触发，无需额外开关。

DDD 定位：domain 的 agent_loop 节点只按 duck-typing 调本服务的两个方法
（ctx.services["agent_tool"]），装配由组合根 web/deps/graph.py 完成。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.call_chain import ensure_chain_allowed
from internal.application.apps.ports import RunnerFactory
from internal.domain.canvas.agent_config import AGENT_TOOL_NAME_PREFIX

logger = logging.getLogger(__name__)

# 子代理答案在结束节点输出里的候选文本键（与 chat_service 主通道取文口径一致）
_ANSWER_TEXT_KEYS = ("output", "content", "answer", "text")
# 模型偶发不用 question 传值时的兼容入参键（与知识库工具 query 兼容策略同构）
_QUESTION_ARG_KEYS = ("question", "input", "text", "query")


class AgentToolService:
    """单个父 run 维度的智能体工具端口：describe / invoke。"""

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
        *,
        tool_name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        """返回 {name, description, parameters}；应用不可用返回 None。

        None 表示该挂载项当前不可用（不存在/不可见/未发布/非智能体），节点侧
        跳过合成工具（配置保留，恢复后可用）。tool_name / description 为
        subAgents 配置项的覆盖值（F14.1/F14.2）。
        """
        card = await self._resolve_target(application_id, chain, enforce_chain=False)
        if card is None:
            return None
        return {
            "name": self._tool_name(card, application_id, tool_name),
            "description": self._tool_description(card, application_id, description),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "委派给该智能体的完整问题；子代理看不到当前会话，须自包含全部背景",
                    },
                },
                "required": ["question"],
            },
        }

    async def invoke(
        self,
        application_id: str,
        arguments: dict[str, Any],
        chain: list[str],
    ) -> str:
        """执行目标智能体并返回最终文本 observation。

        目标不可用/成环/超深/问题为空抛 RuntimeError，由 ReAct 内核转
        [error] observation 回灌模型自纠，不中断对话（与工作流工具同语义）。
        """
        card = await self._resolve_target(application_id, chain, enforce_chain=True)
        if card is None:
            raise RuntimeError(
                f"智能体工具不可用：应用 {application_id} 不存在、不可见、未发布或非智能体类型"
            )
        question = self._delegate_question(arguments)
        if not question:
            raise RuntimeError("委派给智能体的问题不能为空（question 参数缺失）")

        child_thread_id = f"{self._parent_run_id}:sub:{application_id}"
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
        # 子代理输入就是一句话；不传 history——委派语义要求问题自包含（F14.5）
        start_inputs: dict[str, Any] = {
            "input": question,
            "workflow_chain": [*chain, str(application_id)],
        }
        output = await runner.invoke(start_inputs)
        return self._observation_text(card, output)

    async def _resolve_target(
        self,
        application_id: str,
        chain: list[str],
        *,
        enforce_chain: bool,
    ) -> dict[str, Any] | None:
        """鉴权 + 类型 + 发布态（+ 调用链防护）校验，返回应用卡片或 None。

        enforce_chain=False 用于 describe：工具清单可先展示，环/深度在执行时兜底；
        invoke 路径做完整防护（与 WorkflowToolService 同构）。
        """
        try:
            app_id = UUID(str(application_id))
        except (TypeError, ValueError):
            logger.warning("智能体工具 applicationId 非法: %r", application_id)
            return None
        if self._user_id is None:
            logger.warning("智能体工具缺少用户身份，跳过 application=%s", app_id)
            return None
        card = self._app_service.get_visible_app_for_user(app_id, self._tenant_id, self._user_id)
        if card is None or card.get("flow_type") != "agent":
            return None
        # F14.1：目标须已发布；未发布应用 get_runtime_graph 会回退 latest，不能作判据
        if self._app_service.get_published_graph_version(app_id) is None:
            return None
        if enforce_chain:
            ensure_chain_allowed(
                chain, str(app_id), target_name=str(card.get("name") or ""), kind="智能体"
            )
        return card

    @staticmethod
    def _tool_name(
        card: dict[str, Any], application_id: str, tool_name_override: str | None
    ) -> str:
        """工具名：配置 toolName 覆盖优先，否则 agent_{slug}（F14.2）。"""
        override = str(tool_name_override or "").strip()
        if override:
            return override
        return f"{AGENT_TOOL_NAME_PREFIX}{AgentToolService._tool_slug(str(card.get('name') or ''), application_id)}"

    @staticmethod
    def _tool_slug(name: str, application_id: str) -> str:
        """应用名 → 工具名 slug：仅保留 ASCII 字母数字（OpenAI 工具名字符集约束）；

        中文等无 ASCII 名称回退应用 ID 前缀，保证同租户内确定且唯一。
        """
        ascii_slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
        if ascii_slug:
            return ascii_slug[:48]
        return str(application_id).replace("-", "")[:12]

    @staticmethod
    def _tool_description(
        card: dict[str, Any], application_id: str, description_override: str | None
    ) -> str:
        """描述 = 目标应用名 + 说明 + 配置描述覆盖（F14.2），并声明自包含要求。"""
        label = str(card.get("name") or "") or str(application_id)
        detail = (
            str(description_override or "").strip() or str(card.get("description") or "").strip()
        )
        suffix = f"。专长：{detail}" if detail else ""
        return (
            f"把一段完整、自包含的问题委派给智能体「{label}」处理{suffix}。"
            "子代理看不到当前会话，question 必须包含回答所需的全部背景。"
        )

    @staticmethod
    def _delegate_question(arguments: dict[str, Any]) -> str:
        """工具入参取 question；兼容模型误传 input/text/query 的情况。"""
        for key in _QUESTION_ARG_KEYS:
            value = str((arguments or {}).get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _observation_text(card: dict[str, Any], output: Any) -> str:
        """把子 run 终态输出转成委派 observation 文本（取文键与主通道一致）。"""
        label = str(card.get("name") or "")
        if isinstance(output, str):
            return output or f"智能体「{label}」无文本输出"
        if isinstance(output, dict):
            for key in _ANSWER_TEXT_KEYS:
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            if output:
                return json.dumps(output, ensure_ascii=False)
        elif output:
            return json.dumps(output, ensure_ascii=False)
        return f"智能体「{label}」执行完成，无文本输出"
