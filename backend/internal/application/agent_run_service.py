"""Agent 运行用例：加载智能体 + 关联资源，组装 runner 并执行。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.errors import ForbiddenError, NotFoundError
from internal.application.rag_utils import apply_rag_to_prompt
from internal.application.retrieval_service import RetrievalService
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.engine.context import AgentRunContext
from internal.engine.llm import LLMClient, OpenAICompatLLMClient
from internal.engine.memory import ConversationMemory, MemoryKey, build_conversation_memory
from internal.engine.prompt import render_template
from internal.engine.runner import (
    AgentRunResult,
    EventCallback,
    FunctionCallAgentRunner,
    RunnerOptions,
)
from internal.engine.tools import SkillManifest, LoadSkillTool, build_tools

logger = logging.getLogger(__name__)


class AgentRunService:
    """用户端 agent 运行用例。

    加载流程与 UserPortalService.get_agent 对齐：
      - uow 已经叠加 user 端可见范围（apply_user_visibility），agents.get 返回 None 即不可见
      - 工具/技能/组件/提示词按 agent_id + is_enabled 过滤
    短期记忆：按 conversation_id 从 Redis 读取多轮历史；运行结束后回写本轮。
    """

    def __init__(
        self,
        uow: UnitOfWork,
        context: RequestContext,
        llm_factory: Any | None = None,
        memory: ConversationMemory | None = None,
        retrieval_service: RetrievalService | None = None,
    ) -> None:
        self._uow = uow
        self._context = context
        # 测试可注入 mock llm_factory / memory / retrieval；生产从 settings 构造
        self._llm_factory = llm_factory
        self._memory = memory
        self._retrieval_service = retrieval_service

    async def run(
        self,
        *,
        agent_id: UUID,
        query: str,
        conversation_id: str,
        user_id: UUID,
        user_name: str = "",
        history: list[dict[str, Any]] | None = None,
        event_callback: EventCallback | None = None,
    ) -> AgentRunResult:
        """同步运行一次 agent 调用；event_callback 非空时通过它外抛运行事件（SSE 用）。"""
        if self._context.is_platform:
            raise ForbiddenError("用户端仅支持通过租户子域名访问")

        agent = self._uow.agents.get(agent_id)
        if agent is None or not agent.is_enabled:
            raise NotFoundError("智能体不存在或未对当前用户开放")

        tools = self._uow.tools.list_for_agent(agent_id, True)
        prompts = self._uow.prompts.list_for_agent(agent_id, True)
        skills = self._uow.skills.list_for_agent(agent_id, True)

        system_prompt = self._build_system_prompt(agent.config, prompts, skills)
        runtime_tools = build_tools(list(tools))

        # 渐进式披露：把 LoadSkillTool 注入工具列表，让 LLM 按需加载 skill 完整规则
        skill_manifests = [
            SkillManifest(
                name=s.name,
                description=s.description or "",
                content=s.content or "",
            )
            for s in skills
            if s.is_enabled and (s.name or "").strip()
        ]
        if skill_manifests:
            runtime_tools.append(LoadSkillTool(skill_manifests))
        llm_client = self._build_llm_client(agent.config)
        options = self._build_options(agent.config)
        memory = self._resolve_memory()

        run_context = AgentRunContext(
            agent_id=agent_id,
            tenant_id=self._context.tenant_id,
            user_id=user_id,
            user_name=user_name,
            tenant_code=self._context.tenant.code if self._context.tenant else "",
            conversation_id=conversation_id,
        )
        memory_key = MemoryKey(
            tenant_id=self._context.tenant_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )

        # 请求侧显式传 history 时优先用之；否则从 Redis 读短期记忆
        if history:
            history_messages = self._coerce_history(history)
        else:
            history_messages = await memory.load(memory_key)

        # RAG 检索：agent.config.retrieval.enabled=true 时，先召回相关 chunks 注入 prompt
        # 历史消息转 dict 列表传给 query rewriter，用于消解指代（"那它呢"）
        rag_history = self._history_to_dicts(history_messages)
        system_prompt = await self._augment_with_rag(
            system_prompt=system_prompt,
            agent_config=agent.config,
            query=query,
            history=rag_history,
        )

        # 运行期 UoW 拆分：DB 加载阶段结束后立即 commit，把连接归还连接池，
        # 避免 LLM HTTP 循环（可能数十秒）期间一直占用 DB 连接。
        # 后续 Tool 调用走 runtime_tools（已构建好的 Python 对象），不再碰 DB。
        try:
            self._uow.commit()
        except Exception:  # noqa: BLE001 - commit 失败不阻断运行（读阶段无写）
            logger.debug("uow commit after load failed", exc_info=True)

        runner = FunctionCallAgentRunner(
            llm=llm_client,
            tools=runtime_tools,
            system_prompt=system_prompt,
            default_max_iterations=options.max_iterations or 6,
            event_callback=event_callback,
        )

        result = await runner.run(
            query=query,
            history=history_messages,
            context=run_context,
            options=options,
        )

        # 运行成功后把本轮 user + assistant 写回短期记忆（即使请求侧传了 history 也回写，
        # 便于后续无状态调用时仍能延续对话）
        try:
            await memory.append_turn(memory_key, query, result.content)
        except Exception:  # noqa: BLE001 - 记忆写入失败不影响主流程返回
            logger.warning("memory append failed key=%s", memory_key.as_redis_key(), exc_info=True)

        return result

    def _resolve_memory(self) -> ConversationMemory:
        """解析短期记忆实现；测试注入优先，否则从 settings 构造。"""
        if self._memory is not None:
            return self._memory
        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        return build_conversation_memory(
            settings.redis_url,
            max_turns=settings.memory_max_turns,
            ttl_seconds=settings.memory_ttl_seconds,
        )

    def _build_system_prompt(
        self,
        agent_config: dict[str, Any],
        prompts: list[Any],
        skills: list[Any] | None = None,
    ) -> str:
        """拼装系统提示词：主提示词 + 预加载启用 skills 完整规则。

        优先级：
        1. agent.config.system_prompt 显式覆盖
        2. prompts 表中 category=system 的首个启用项
        3. 兜底：智能体描述
        末尾追加启用 skills 的完整执行规则，让 LLM 直接按 skill 规则执行，
        无需 XML 标签路由。
        """
        base = str(agent_config.get("system_prompt") or "").strip()
        if not base:
            for prompt in prompts:
                if (prompt.category or "").lower() == "system":
                    base = prompt.content or ""
                    break
        if not base:
            base = "你是一个乐于助人的智能助手。"

        variables: dict[str, Any] = {
            "tenant_id": str(self._context.tenant_id or ""),
            "tenant_code": self._context.tenant.code if self._context.tenant else "",
        }
        extra = agent_config.get("prompt_variables") or {}
        if isinstance(extra, dict):
            variables.update({str(k): v for k, v in extra.items()})
        system_prompt = render_template(base, variables)

        skills_section = self._build_skills_section(skills or [])
        if skills_section:
            system_prompt = f"{system_prompt}\n\n{skills_section}"

        return system_prompt

    @staticmethod
    def _build_skills_section(skills: list[Any]) -> str:
        """渐进式披露：只输出技能清单（name + description），不输出完整规则。

        完整规则由 LoadSkillTool 按需加载，避免 system prompt 被全量 skill 撑爆。
        """
        if not skills:
            return ""
        blocks: list[str] = [
            "# 可用技能库",
            "本智能体装配了以下技能。当需要使用某个技能时，"
            "必须先调用 `load_skill` 工具加载该技能的完整执行规则，再按规则执行任务。",
            "",
            "| 技能名 | 简介 |",
            "|---|---|",
        ]
        for skill in skills:
            name = (skill.name or "").strip()
            if not name:
                continue
            description = (skill.description or "").strip() or "（无简介）"
            blocks.append(f"| `{name}` | {description} |")
        return "\n".join(blocks)

    async def _augment_with_rag(
        self,
        *,
        system_prompt: str,
        agent_config: dict[str, Any],
        query: str,
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        """RAG 增强：启用时召回相关 chunks，拼到 system_prompt 后面。"""
        return await apply_rag_to_prompt(
            system_prompt=system_prompt,
            retrieval_cfg=agent_config.get("retrieval") or {},
            query=query,
            uow=self._uow,
            context=self._context,
            history=history,
            retrieval_service=self._retrieval_service,
        )

    @staticmethod
    def _history_to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
        """把内部 ChatMessage 列表转成 dict 列表，供 query rewriter 使用。"""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            if not role or not content:
                continue
            result.append({"role": role, "content": content})
        return result

    def _build_llm_client(self, agent_config: dict[str, Any]) -> LLMClient:
        """构造 LLM 客户端；测试可注入 llm_factory 覆盖。"""
        if self._llm_factory is not None:
            return self._llm_factory(agent_config)
        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        return OpenAICompatLLMClient(
            api_key=settings.llm_api_key.get_secret_value(),
            model=str(agent_config.get("model_id") or settings.llm_model_id),
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            default_temperature=float(
                agent_config.get("temperature") or settings.llm_temperature
            ),
            default_max_tokens=int(agent_config.get("max_tokens") or settings.llm_max_tokens),
        )

    @staticmethod
    def _build_options(agent_config: dict[str, Any]) -> RunnerOptions:
        """从 agent.config 抽取运行期可覆盖参数。"""
        return RunnerOptions(
            temperature=agent_config.get("temperature"),
            max_tokens=agent_config.get("max_tokens"),
            max_iterations=agent_config.get("max_iterations"),
        )

    @staticmethod
    def _coerce_history(history: list[dict[str, Any]]) -> list[Any]:
        """把请求侧的历史消息 dict 列表转换为内部消息模型。

        当前只支持 user / assistant 两种角色的纯文本历史；tool 消息由 runner 自维护。
        """
        from internal.engine.messages import AssistantMessage, UserMessage

        messages: list[Any] = []
        for item in history:
            role = item.get("role")
            content = str(item.get("content") or "")
            if role == "user":
                messages.append(UserMessage(content=content))
            elif role == "assistant":
                messages.append(AssistantMessage(content=content))
            # system / tool 历史暂不支持，避免污染上下文
        return messages
