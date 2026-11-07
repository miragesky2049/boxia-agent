"""用户端 chat 应用服务：ReAct 循环 + SSE 事件流 + 会话/消息持久化。

chat 支持两条执行通道（20261106 P3 服务端兼容契约）：
- 画布通道：应用有 agent_loop 节点且关键配置显式（tools 或 datasets/modleName/systemPrompt）时，
  走 GraphRuntime 执行 start→agent_loop(react_only)→end，把画布 trace 事件映射为
  既有 chat SSE 帧契约，前端 agentRun.ts 消费不变；run 表/节点审计/checkpoint
  作为运行时副产品获得。
- 进程内通道：无 tools 的打字机流式、以及配置不满足上述条件的旧应用，直接消费
  共享 ReAct 内核（`internal.domain.agent.react.run_react_loop`），保持改造前行为。
两条通道循环语义同源一份内核，工具执行共用 ToolExecutorService → ToolGateway 链路。

0074 PRD F10 人审（M3）：画布通道内 agent_loop 节点按 sensitiveTools 声明整轮挂起时，
本服务把审批信息与执行快照存进 run.interrupt_payload 并推 interrupted SSE 帧；
用户裁决后经同一入口带 resume 续跑（复用被挂起的 run 行、全新 invoke 从快照还原）。
全程不使用 langgraph 挂起中断，R6 断连清理语义不受影响。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.apps.ports import RunnerFactory
from internal.application.apps.resource_service import AppResourceService
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.agent.memory import (
    normalize_history_rows,
    parse_memory_config,
    trim_history,
)
from internal.domain.agent.react import (
    ToolExecutor,
    build_tool_specs,
    empty_usage,
    run_react_loop,
)
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.canvas.convert import find_agent_loop_config
from internal.domain.llm.client import LLMToolSpec
from internal.domain.repository.apps_protocols import (
    ConversationRepositoryProtocol,
    MessageRepositoryProtocol,
    RunRepositoryProtocol,
)
from internal.domain.repository.protocols import UnitOfWork

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10


def _to_int(value: Any) -> int | None:
    """配置项安全转 int；非法值或非正数返回 None 交由调用方走默认值。

    20261106 review 修正：0/负数视为未配置（工具轮次没有合法消费场景），
    与 web/user/routers/agents.py 详情卡片同名函数保持逐字节一致的解析语义。
    """
    try:
        result = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result > 0 else None


def _extract_final_text(output: Any) -> str:
    """从结束节点输出里取最终回答文本；返回变量模式可能没有文本。"""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("output", "content", "answer", "text"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _resume_answer_text(resume: dict[str, Any] | None) -> str:
    """从 resume 载荷里取用户回答文本；人审批准等非回答载荷返回空。"""
    if not isinstance(resume, dict):
        return ""
    value = resume.get("answer", resume.get("content"))
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _approval_decision_text(approved: bool, comment: str) -> str:
    """0074 PRD F10：审批裁决转用户消息文案（落会话历史，恢复时上下文可读）。"""
    base = "批准执行工具调用" if approved else "拒绝执行工具调用"
    return f"{base}（理由：{comment}）" if comment else base


def _parse_phase_json(text: str) -> Any:
    """plan/reflect 阶段的模型输出是 JSON 文本；解析失败返回 None（原样透出不影响展示）。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


@dataclass
class _ChatRunState:
    """chat 单轮执行累加状态：画布/进程内两条通道共用，落库与 result 帧统一消费。"""

    final_content: str = ""
    assistant_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_traces: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    usage_total: dict[str, int] = field(default_factory=empty_usage)
    finish_reason: str = "stop"
    run_id: UUID | None = None
    # 画布通道守卫：agent_loop 节点是否真正执行完成（缺连线/图不可达时不能静默空回答）
    agent_finished: bool = False
    # 0074 PRD F10：画布节点整轮挂起时的审批现场 {approval, snapshot}
    awaiting: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ChatRunSpec:
    """chat 单轮执行计划：由 _build_chat_run_plan 从画布配置解析产出，通道 helper 消费。"""

    application_id: UUID
    cid: UUID
    query: str
    history: list[dict[str, str]] | None
    system_prompt: str
    model_id: str
    tool_specs: list[LLMToolSpec]
    max_rounds: int
    run_id: UUID
    use_canvas: bool
    # 画布通道 node_end 完成判定用（20261106 review 修正：按节点 ID 精确匹配，
    # 不再嗅探输出键名）
    loop_node_id: str = ""
    # 0074 PRD F4：深度模式（reasoningMode=planExecuteReflect）时画布通道
    # 不再传 react_only，节点内 plan/execute/reflect 三阶段完整执行
    react_only: bool = True
    # 0074 PRD F9：多模态图片 URL 列表（节点侧按 visionEnabled 门控后使用）
    images: list[str] | None = None
    # 0074 PRD F10：审批续跑载荷 {approved, comment, snapshot}；None = 常规新轮
    approval_resume: dict[str, Any] | None = None
    # 画布通道线程 ID：默认会话 ID；新消息遇到未决审批时轮转为子线程
    thread_id: str = ""


@dataclass(frozen=True)
class ChatflowPreparedRun:
    """对话流请求级校验后的运行上下文。

    HTTP 路由在返回 StreamingResponse 之前调用 prepare_chatflow_run，
    会话/线程/参数错误直接以 4xx 返回，不再落进 SSE error 事件。
    """

    application_id: UUID
    message: str
    conversation_id: UUID
    conversation_title: str
    thread_id: str
    resume: dict[str, Any] | None


class ChatService:
    """user 端 chat 服务：组装 LLM + tools + 历史消息，跑 ReAct 循环并产出 SSE 事件。"""

    def __init__(
        self,
        uow: UnitOfWork,
        context: Any,
        principal: Any,
        runner_factory: RunnerFactory,
        *,
        app_service: ApplicationService,
        model_service: ModelService,
        resource_service: AppResourceService,
        conv_repo: ConversationRepositoryProtocol,
        msg_repo: MessageRepositoryProtocol,
        run_repo: RunRepositoryProtocol,
        default_llm_model_id: str,
        tool_executor_factory: Callable[[UUID, UUID | str], ToolExecutor],
    ) -> None:
        """runner_factory 与各服务/仓储由组合根注入（web.deps.graph / apps_services），
        应用层不自行构造 infra 具体类，也不反向 import web。
        tool_executor_factory 按 (application_id, run_id) 构造工具执行器
        （组合根用 ToolExecutorService 实现，与画布同一套 HttpTool/McpTool/网关链路）。"""
        self._uow = uow
        self._context = context
        self._principal = principal
        self._runner_factory = runner_factory
        self._tenant_id = principal.tenant_id
        self._user_id = principal.user_id
        self._app_service = app_service
        self._model_service = model_service
        self._resource_service = resource_service
        self._conv_repo: ConversationRepositoryProtocol = conv_repo
        self._msg_repo: MessageRepositoryProtocol = msg_repo
        self._run_repo: RunRepositoryProtocol = run_repo
        self._default_llm_model_id = default_llm_model_id
        self._tool_executor_factory = tool_executor_factory

    def _resolve_chat_conversation(
        self,
        application_id: UUID,
        conversation_id: UUID | None,
        query: str,
    ) -> UUID:
        """校验会话归属；未指定会话 ID 时新建会话（行为与改造前一致）。"""
        if conversation_id is not None:
            conv = self._conv_repo.get_conversation(conversation_id)
            if (
                conv is None
                or conv["user_id"] != self._user_id
                or conv["application_id"] != application_id
                or conv["tenant_id"] != self._tenant_id
            ):
                raise NotFoundError("会话不存在或无权访问")
            return conversation_id
        return self._conv_repo.insert_conversation(
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=application_id,
            title=query[:30],
        )

    # ========== chat SSE ==========
    async def run_agent_stream(
        self,
        application_id: UUID,
        query: str,
        conversation_id: UUID | None,
        history: list[dict[str, str]] | None,
        *,
        images: list[str] | None = None,
        resume: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """跑一轮 ReAct 对话，产出 (event_name, payload) 序列。路由层负责转 SSE 帧。

        20261106 P3：读完画布配置后决定执行通道——满足画布条件走 GraphRuntime
        （trace 事件映射为同帧契约），否则保持改造前的进程内内核/打字机通道。
        0074 PRD F10（M3）：resume={approved, comment} 时找到挂起的 tool_approval
        run 并从其快照续跑（复用被挂起的 run 行）；挂起本轮以 interrupted 帧收尾，
        不落 assistant 消息、不发 result。F9：images 透传节点按 visionEnabled 门控。
        """
        # 1. 可见性闸门
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )

        # 2. 会话归属
        cid = self._resolve_chat_conversation(application_id, conversation_id, query)

        # 3. 定位该线程上挂起的工具审批（快照挂在 run.interrupt_payload，与 checkpoint 无关）
        bound_thread = self._bind_chatflow_thread_id(cid, thread_id)
        pending = self._find_pending_tool_approval(application_id, bound_thread)

        approval_resume: dict[str, Any] | None = None
        run_id = uuid4()
        if resume is not None:
            if pending is None:
                raise ValidationError("没有待恢复的工具审批")
            approval_resume = {
                "approved": bool(resume.get("approved")),
                "comment": str(resume.get("comment") or ""),
                "snapshot": (pending["payload"] or {}).get("snapshot"),
            }
            # 续跑复用被挂起的 run 行：审计字段连续 + message.run_id 外键可解析
            # （与对话流 resume 同形）；invoke 终态会经 update_run_status 清 payload
            run_id = pending["run_id"]
            # 裁决文案作为 user 消息落库；快照续跑路径会忽略该入参
            query = _approval_decision_text(approval_resume["approved"], approval_resume["comment"])
            # 快照自带完整执行现场，不再拉取服务端记忆/携带历史
            history = []
        elif pending is not None:
            # 新消息遇到未决审批：轮转子线程，保证旧挂起 run 的 resume 检索
            # （get_running_by_thread 按 thread 取最近未结束行）不被本轮干扰
            bound_thread = f"{cid}:{uuid4()}"

        state = _ChatRunState()

        try:
            # 4. 读画布 agent_loop 配置 -> 执行计划（配置键收口与通道判定见 _build_chat_run_plan）
            graph = await self._app_service.get_runtime_graph(application_id, self._tenant_id)
            spec = self._build_chat_run_plan(
                app_card=app_card,
                graph=graph,
                application_id=application_id,
                query=query,
                cid=cid,
                history=history,
                run_id=run_id,
                images=images,
                approval_resume=approval_resume,
                thread_id=bound_thread,
            )
            if approval_resume is not None and not spec.use_canvas:
                raise ValidationError("当前应用未走画布执行通道，无法恢复审批")

            if not spec.use_canvas:
                # 5. 落库 user 消息（画布通道在 ensure_run 后绑定 run_id 另行落库）
                self._msg_repo.append_message(
                    conversation_id=cid,
                    tenant_id=self._tenant_id,
                    user_id=self._user_id,
                    application_id=application_id,
                    role="user",
                    content=query,
                )

            yield "run_start", {
                "run_id": str(run_id),
                "tools": [t.name for t in spec.tool_specs],
            }

            # 6. 三条通道（SSE 事件契约一致，仅执行载体不同）。
            # 0074 PRD F5 校准：use_canvas 优先于 tools 判空——纯知识库 agent 的
            # tools 为空但 knowledge_search_N 合成工具只存在于画布节点内，
            # 若先走打字机分支会整体跳过检索。
            if spec.use_canvas:
                async for frame in self._run_agent_via_canvas(spec, state):
                    yield frame
            elif not spec.tool_specs:
                async for frame in self._run_typewriter_stream(spec, state):
                    yield frame
            else:
                async for frame in self._run_kernel_inprocess_stream(spec, state):
                    yield frame

            if state.awaiting is not None:
                # 7a. F10 挂起收尾：快照入 run payload、置 interrupted、推 interrupted 帧；
                # 本轮不落 assistant 消息也不发 result（审批对象不能伪装成最终回答）
                async for frame in self._emit_approval_interrupt(spec, state):
                    yield frame
            else:
                # 7b. 落库 assistant 消息（进程内通道不走 run 表 run_id 置空；画布通道绑定本轮 run）
                self._msg_repo.append_message(
                    conversation_id=cid,
                    tenant_id=self._tenant_id,
                    user_id=self._user_id,
                    application_id=application_id,
                    role="assistant",
                    content=state.final_content,
                    tool_calls=state.assistant_tool_calls or None,
                    run_id=state.run_id,
                    metadata={"usage": state.usage_total, "iterations": state.iterations},
                )

                yield "result", {
                    "agent_id": str(application_id),
                    "run_id": str(run_id),
                    "conversation_id": str(cid),
                    "content": state.final_content,
                    "tool_traces": state.tool_traces,
                    "iterations": state.iterations,
                    "usage": state.usage_total,
                    "finish_reason": state.finish_reason,
                }
                # 消息落库后统一提交，HTTP 层无需再 commit
                self._uow.commit()
        except Exception as exc:
            logger.exception("chat 运行失败 application=%s", application_id)
            yield "error", {"message": str(exc), "code": "chat_failed"}
        finally:
            yield "final", {}

    def _build_chat_run_plan(
        self,
        *,
        app_card: dict[str, Any],
        graph: dict[str, Any],
        application_id: UUID,
        query: str,
        cid: UUID,
        history: list[dict[str, str]] | None,
        run_id: UUID,
        images: list[str] | None = None,
        approval_resume: dict[str, Any] | None = None,
        thread_id: str = "",
    ) -> _ChatRunSpec:
        """从画布 agent_loop 配置解析执行计划（20260731 配置键收口 + 20261106 P3 通道判定）。

        配置键以画布 coze 命名（systemPrompt/modleName/tools/maxToolRounds）为准，
        旧 snake_case 键保留一个迭代周期的兼容读取。仅当画布节点能完整复刻旧 chat
        行为才交棒 GraphRuntime：
        - tools 必须画布显式声明（legacy tool_resource_ids 兜底出的节点读不到）；
        - modleName 显式（旧通道缺省回退 default_llm_model_id，节点拿不到该回退值）；
        - camelCase systemPrompt 显式（节点只认 camel；旧通道回退应用名 prompt 时
          两侧拼出的 system 消息不同）。

        20261106 冒烟修正：画布持久化是 coze 数字形态（type "100" + data.inputs），
        节点定位与配置解析统一走 find_agent_loop_config（与 AgentLoopNodeHandler
        同一份 convert 口径），不再按 {"type":"agent_loop","config"} 假设形态读取。
        """
        loop_config = find_agent_loop_config(graph)
        loop_node_id = loop_config[0] if loop_config else ""
        node_cfg = loop_config[1] if loop_config else {}
        system_prompt = (
            node_cfg.get("systemPrompt")
            or node_cfg.get("system_prompt")
            or f"你是{app_card['name']}。{app_card.get('description') or ''}".strip()
        )
        model_id = (
            node_cfg.get("modleName")
            or node_cfg.get("modelName")
            or node_cfg.get("model_id")
            or self._default_llm_model_id
        )
        canvas_tool_specs = build_tool_specs(node_cfg.get("tools"))
        tool_specs = canvas_tool_specs or self._legacy_tool_specs(
            node_cfg.get("tool_resource_ids") or []
        )
        max_rounds = (
            _to_int(node_cfg.get("maxToolRounds"))
            or _to_int(node_cfg.get("max_tool_rounds"))
            or MAX_TOOL_ROUNDS
        )
        # 0074 PRD v1.2 校准：纯知识库 agent（无普通 tools）也必须走画布通道，
        # 否则 knowledge_search_N 合成工具只在节点内存在、旧通道执行不到检索；
        # M2 同因把 MCP 快照（F6）与工作流挂载（F7）计入判据——它们的工具
        # 同样只在画布节点内合成
        datasets_cfg = node_cfg.get("datasets")
        use_canvas = bool(
            loop_node_id
            and (
                canvas_tool_specs
                or datasets_cfg
                or node_cfg.get("mcpServers")
                or node_cfg.get("workflows")
            )
            and (node_cfg.get("modleName") or node_cfg.get("modelName"))
            and node_cfg.get("systemPrompt")
        )
        # 0074 PRD F8：agent 型服务端记忆——前端未传 history 时按节点 memory 配置拉取
        if history is None and app_card.get("flow_type") == "agent" and cid is not None:
            history = self._load_agent_memory(node_cfg, cid)
        # 0074 PRD F4.1：深度模式开关。仅 agent 型且显式选择 planExecuteReflect 时
        # 放开节点内 plan/reflect 三阶段；其余（含存量应用无该键）保持 react_only=True
        # 的既有成本与语义。
        react_only = not (
            app_card.get("flow_type") == "agent"
            and use_canvas
            and str(node_cfg.get("reasoningMode") or "") == "planExecuteReflect"
        )
        return _ChatRunSpec(
            application_id=application_id,
            cid=cid,
            query=query,
            history=history,
            system_prompt=system_prompt,
            model_id=model_id,
            tool_specs=tool_specs,
            max_rounds=max_rounds,
            run_id=run_id,
            use_canvas=use_canvas,
            loop_node_id=loop_node_id,
            react_only=react_only,
            images=list(images or []),
            approval_resume=approval_resume,
            thread_id=thread_id or str(cid),
        )

    def _load_agent_memory(self, node_cfg: dict[str, Any], cid: UUID) -> list[dict[str, str]]:
        """按画布 memory 配置从 message 表拉取并截断短期记忆（0074 PRD F8）。

        组装点统一在 ChatService（画布/进程内两条通道经 spec.history 同获），
        截断纯逻辑在 domain/agent/memory；拉取失败降级为无历史继续对话，
        只记告警——记忆缺失可容忍，直接报错会让用户连基本对话都发不起。
        """
        memory = parse_memory_config(node_cfg.get("memory"))
        if not memory["enabled"]:
            return []
        list_fn = getattr(self._msg_repo, "list_messages_by_conversation", None)
        if list_fn is None:
            logger.warning("msg_repo 未实现 list_messages_by_conversation，跳过服务端记忆")
            return []
        try:
            rows = list_fn(cid, limit=memory["windowTurns"] * 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("服务端记忆拉取失败 conversation=%s: %s", cid, exc)
            return []
        return trim_history(
            normalize_history_rows(rows),
            window_turns=memory["windowTurns"],
            token_budget=memory["tokenBudget"],
        )

    async def _run_typewriter_stream(
        self,
        spec: _ChatRunSpec,
        state: _ChatRunState,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """进程内通道（无 tools）：逐 token yield llm_token，前端打字机渲染。"""
        client = self._model_service.get_client_for_tenant(spec.model_id, self._tenant_id)
        messages = self._build_chat_messages(spec.system_prompt, spec.query, spec.history)
        state.iterations = 1
        yield "llm_start", {
            "iteration": state.iterations,
            "messages": messages,
            "tools": [],
        }

        chunks: list[str] = []
        async for chunk in client.chat_stream(messages=messages):
            delta = chunk.content or ""
            if delta:
                chunks.append(delta)
                yield "llm_token", {
                    "delta": delta,
                }
            if chunk.usage.prompt_tokens:
                state.usage_total = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }
            if chunk.finish_reason:
                state.finish_reason = chunk.finish_reason

        state.final_content = "".join(chunks)
        yield "llm_end", {
            "iteration": state.iterations,
            "content": state.final_content,
            "tool_calls": [],
            "usage": dict(state.usage_total),
        }

    async def _run_kernel_inprocess_stream(
        self,
        spec: _ChatRunSpec,
        state: _ChatRunState,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """进程内通道（有 tools）：循环本体在 react.run_react_loop，本方法只做
        内核事件 -> chat SSE 契约的映射（事件名与字段与合并前逐一对齐）。"""
        client = self._model_service.get_client_for_tenant(spec.model_id, self._tenant_id)
        messages = self._build_chat_messages(spec.system_prompt, spec.query, spec.history)
        run_context = AgentRunContext(
            agent_id=spec.application_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            conversation_id=str(spec.cid),
            run_id=str(spec.run_id),
        )
        async for event in run_react_loop(
            llm=client,
            messages=messages,
            tool_specs=spec.tool_specs,
            tool_executor=self._tool_executor_factory(spec.application_id, spec.run_id),
            max_rounds=spec.max_rounds,
            chat_kwargs={"context": run_context},
        ):
            payload = event.payload
            if event.kind == "llm_start":
                yield "llm_start", {
                    "iteration": payload["iteration"],
                    "messages": payload["messages"],
                    "tools": payload["tools"],
                }
            elif event.kind == "llm_end":
                state.assistant_tool_calls = payload["tool_calls"]
                yield "llm_end", {
                    "iteration": payload["iteration"],
                    "content": payload["content"],
                    "tool_calls": payload["tool_calls"],
                    "usage": payload["usage"],
                }
            elif event.kind == "tool_start":
                yield "tool_start", {
                    "tool_call_id": payload["tool_call_id"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                }
            elif event.kind == "tool_end":
                yield "tool_end", {
                    "tool_call_id": payload["tool_call_id"],
                    "name": payload["name"],
                    "observation": payload["observation"],
                    "is_error": payload["is_error"],
                }
            elif event.kind == "result":
                state.final_content = payload["content"]
                state.tool_traces = payload["tool_traces"]
                state.iterations = payload["iterations"]
                state.usage_total = payload["usage"]
                state.finish_reason = payload["finish_reason"]

    async def _run_agent_via_canvas(
        self,
        spec: _ChatRunSpec,
        state: _ChatRunState,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """chat 驱动画布执行（20261106 P3 服务端兼容契约）。

        以 GraphRuntime 跑 start→agent_loop(react_only)→end，把画布 trace 事件
        映射为既有 chat SSE 帧契约（前端不动）；run 表、节点执行记录、checkpoint
        是运行时副产品。异常统一上抛，由 run_agent_stream 外层产出 error 帧。
        """
        run_context = AgentRunContext(
            agent_id=spec.application_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            conversation_id=str(spec.cid),
            run_id=str(spec.run_id),
        )
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def emitter(event_type: str, payload: dict[str, Any]) -> None:
            await queue.put(("event", (event_type, payload)))

        runner = await self._runner_factory(
            self._app_service,
            self._uow,
            self._context,
            tenant_id=self._tenant_id,
            application_id=spec.application_id,
            # 0074 PRD F10：线程由 run_agent_stream 绑定（默认会话 ID，
            # 新消息遇未决审批轮转子线程，resume 沿用挂起 run 的线程）
            thread_id=spec.thread_id or str(spec.cid),
            run_id=spec.run_id,
            current_user_id=self._user_id,
            actor_username=getattr(self._principal, "username", None),
            conversation_id=spec.cid,
            on_node_event=emitter,
        )
        start_inputs: dict[str, Any] = {
            "input": spec.query,
            "USER_INPUT": spec.query,
            "history": [dict(h) for h in spec.history or []],
            "max_tool_rounds": spec.max_rounds,
            # AgentRunContext 经节点透传 LLM 请求头；与画布试运行共用同一条注入通道
            # （ctx.eval_context.input），画布试运行不传即为缺省。
            # 20261106 review 修正：start_inputs 会进 run 表 JSONB（insert_run 裸
            # json.dumps），必须传 to_storage_dict 平铺形态，节点侧还原。
            "context": run_context.to_storage_dict(),
            # 0074 PRD F4.1：深度模式下为 False，节点走完整 plan/execute/reflect
            "react_only": spec.react_only,
            # 0074 PRD F9：图片 URL 透传，节点按 visionEnabled 门控
            "images": list(spec.images or []),
        }
        if spec.approval_resume is not None:
            # 0074 PRD F10：审批裁决 + 执行快照，节点从快照还原续跑（非法快照按新 run 兜底）
            start_inputs["approval_resume"] = spec.approval_resume
        runner.ensure_run(start_inputs)
        state.run_id = runner.run_id
        self._msg_repo.append_message(
            conversation_id=spec.cid,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=spec.application_id,
            role="user",
            content=spec.query,
            run_id=runner.run_id,
        )

        async def run_task() -> None:
            try:
                await runner.invoke(start_inputs)
            except Exception as exc:  # noqa: BLE001 - 主循环统一转 error 帧
                queue.put_nowait(("error", exc))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(run_task())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "done":
                    break
                if kind == "error":
                    raise payload
                event_type, data = payload
                for frame in self._map_canvas_trace(event_type, data or {}, state, spec.loop_node_id):
                    yield frame
        finally:
            # task 未结束即退出循环 = 消费侧被拆（SSE 断连 GeneratorExit / 请求
            # 任务取消）；error 帧路径 run_task 必先完成（无 await 收尾），不误判
            abandoned = not task.done()
            if abandoned:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            if abandoned:
                await self._abandon_canvas_run(runner)

        # 守卫：图里没有执行到 agent_loop（缺连线/仅停用未删节点等）时显式报错，
        # 不能带着空回答落库（画布通道判定只查节点存在，不保证图连通）
        if not state.agent_finished:
            raise RuntimeError("画布未执行到 agent_loop 节点，请检查 start→agent_loop→end 连线")

    async def _abandon_canvas_run(self, runner: Any) -> None:
        """断连取消后的画布 run 收口（0074 PRD 风险 R6，M2）。

        两步：
        1. run 标记 cancelled 并提交——顺带落盘本请求已写的 run 行与 user 消息，
           否则连接关闭回滚，日志页只能看到"消失的一轮"；
        2. 清理该 thread 的幽灵 checkpoint——agent 对话通道的多轮上下文由 history
           入参显式携带、agent 画布图（白名单 start/agent_loop/end）无 human_task
           中断点，下一轮不依赖 checkpoint 续跑，残留只会带来脏读与存储浪费。
        0074 PRD F10 补充：工具审批的执行快照存 run.interrupt_payload 而非
        checkpoint，purge 不影响已挂起审批的恢复。
        两步失败都只吞不抛：主流程本就是断连拆除，异常无处可报。
        """
        with contextlib.suppress(Exception):
            self._run_repo.update_run_status(
                runner.run_id,
                execute_status="cancelled",
                error_message="客户端断连，执行已取消",
            )
            self._uow.commit()
        with contextlib.suppress(Exception):
            await runner.purge_thread_checkpoints()

    def _find_pending_tool_approval(self, application_id: UUID, thread_id: str) -> dict[str, Any] | None:
        """0074 PRD F10：查线程上挂起的工具审批 run；无（或类型不符）返回 None。

        返回 {run_id, payload}：run_id 供续跑复用，payload 含审批展示字段与执行快照。
        interrupt_payload 兼容 JSONB 反序列化差异（dict / 字符串两种形态）。
        协议兼容：duck-typing 场景（轻量 fake/旧实现）缺查询方法按无挂起处理。
        """
        finder = getattr(self._run_repo, "get_running_by_thread", None)
        if finder is None:
            return None
        running = finder(self._tenant_id, application_id, thread_id)
        if running is None or running.get("execute_status") != "interrupted":
            return None
        payload = running.get("interrupt_payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload or "{}")
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict) or payload.get("type") != "tool_approval":
            return None
        return {"run_id": running["id"], "payload": payload}

    async def _emit_approval_interrupt(
        self,
        spec: _ChatRunSpec,
        state: _ChatRunState,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """0074 PRD F10：挂起收尾——审批信息与快照写入 run 并推 interrupted 帧。

        帧内 approval 为展示裁剪形态（节点已不含 snapshot 键），快照只进库不外发，
        避免大负载走 SSE；run 置 interrupted 后由 update_run_interrupt 落 payload，
        续跑终态经 update_run_status 自动清理。
        """
        awaiting = state.awaiting or {}
        approval = dict(awaiting.get("approval") or {})
        snapshot = awaiting.get("snapshot") or {}
        run_id = state.run_id or spec.run_id
        self._run_repo.update_run_interrupt(run_id, {**approval, "snapshot": snapshot})
        # 挂起现场（run 行 + user 消息 + payload）先提交：随后即使断连也不丢审批
        self._uow.commit()
        yield "interrupted", {
            "approval": approval,
            "conversation_id": str(spec.cid),
            "thread_id": spec.thread_id or str(spec.cid),
            "run_id": str(run_id),
        }

    @staticmethod
    def _map_canvas_trace(
        event_type: str,
        data: dict[str, Any],
        state: _ChatRunState,
        loop_node_id: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """画布 trace 事件 -> chat SSE 帧映射，字段与进程内内核分支逐一对齐。

        已知可接受偏差：llm_start.messages 走画布 trace 的 4000 字符截断形态
        （前端 agentRun.ts 忽略 llm_start，不影响渲染）；画布无 token 级流
        （与旧 tools 分支一致，旧分支本就没有 llm_token）。
        """
        # 0074 PRD F4.1：深度模式的 plan/reflect 结果透出为 additive SSE 事件
        # （前端不识别时安全忽略；仅 assistant 回复帧外发，请求帧不发，避免刷屏）
        if event_type == "prompt_text" and data.get("phase") in ("plan", "reflect"):
            if data.get("role") != "assistant":
                return []
            raw = str(data.get("content") or "")
            frame_type = str(data.get("phase"))
            payload: dict[str, Any] = {"content": raw}
            if frame_type == "reflect":
                payload["reflect_round"] = int(data.get("reflect_round") or 0)
            parsed = _parse_phase_json(raw)
            if frame_type == "plan":
                tasks = parsed.get("tasks") if isinstance(parsed, dict) else None
                payload["tasks"] = [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []
            elif isinstance(parsed, dict):
                payload["done"] = bool(parsed.get("done"))
                payload["critique"] = str(parsed.get("critique") or "")
                payload["suggestion"] = str(parsed.get("suggestion") or "")
            return [(frame_type, payload)]
        if event_type == "prompt_text" and data.get("phase") == "execute":
            iteration = int(data.get("iteration") or 0)
            state.iterations = max(state.iterations, iteration)
            if data.get("role") == "assistant":
                finish_reason = data.get("finish_reason")
                if finish_reason:
                    state.finish_reason = str(finish_reason)
                tool_calls = list(data.get("tool_calls") or [])
                state.assistant_tool_calls = tool_calls
                usage = data.get("usage")
                return [("llm_end", {
                    "iteration": iteration,
                    "content": data.get("content") or "",
                    "tool_calls": tool_calls,
                    "usage": dict(usage) if isinstance(usage, dict) else empty_usage(),
                })]
            if data.get("messages") is not None:
                return [("llm_start", {
                    "iteration": iteration,
                    "messages": data.get("messages") or [],
                    "tools": data.get("tools") or [],
                })]
            return []
        if event_type == "tool_call_start":
            return [("tool_start", {
                "tool_call_id": data.get("tool_call_id"),
                "name": data.get("name"),
                "arguments": data.get("arguments_parsed") or {},
            })]
        if event_type == "tool_call_end":
            state.tool_traces.append({
                "tool_call_id": data.get("tool_call_id"),
                "name": data.get("name"),
                "observation": data.get("observation"),
                "is_error": bool(data.get("is_error")),
            })
            chunks_meta = data.get("chunks_meta")
            return [("tool_end", {
                "tool_call_id": data.get("tool_call_id"),
                "name": data.get("name"),
                "observation": data.get("observation"),
                "is_error": bool(data.get("is_error")),
                # 0074 PRD F5.3：知识库命中来源（additive，仅检索工具携带）
                **({"chunks": chunks_meta} if isinstance(chunks_meta, list) and chunks_meta else {}),
            })]
        if event_type == "node_end" and data.get("status") == "success":
            # 20261106 review 修正：以 agent_loop 节点 ID 精确匹配完成事件，
            # 不再按输出键名嗅探（end/subworkflow 节点可能恰好带 plan/output 键，
            # 而节点输出结构一旦调整又会误判"未执行"）
            if not loop_node_id or str(data.get("node_id") or "") != loop_node_id:
                return []
            outputs = data.get("outputs")
            if isinstance(outputs, dict):
                if outputs.get("awaiting_approval"):
                    # 0074 PRD F10：节点整轮挂起等待人工批准。agent_finished 仍置 True
                    # （节点确实执行到位），审批现场经 state.awaiting 交回收尾
                    state.agent_finished = True
                    state.awaiting = {
                        "approval": outputs.get("approval") or {},
                        "snapshot": outputs.get("snapshot") or {},
                    }
                    return []
                state.final_content = str(outputs.get("output") or "")
                state.agent_finished = True
                usage = outputs.get("usage")
                if isinstance(usage, dict):
                    state.usage_total = usage
                # 0074 PRD F11.1：节点透出 finish_reason 时覆盖默认 stop（当前仅预算触顶）
                finish_reason = outputs.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason:
                    state.finish_reason = finish_reason
        return []

    @staticmethod
    def _build_chat_messages(
        system_prompt: str,
        query: str,
        history: list[dict[str, str]] | None,
    ) -> list[dict[str, Any]]:
        """进程内通道的 messages 组装：system + 过滤后的多轮历史 + 当前问题。"""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for h in history or []:
            role = h.get("role")
            content = h.get("content") or ""
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": query})
        return messages

    # ========== 会话历史读取 ==========
    async def list_conversations(
        self,
        application_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出当前用户在指定应用下的会话列表（按 updated_at 倒序）。"""
        self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        rows = self._conv_repo.list_conversations_by_user(
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=application_id,
            channel="api",
            limit=limit,
            offset=offset,
        )
        return [
            {
                "conversation_id": str(r["id"]),
                "title": r.get("title") or "",
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
            for r in rows
        ]

    async def list_messages(
        self,
        application_id: UUID,
        conversation_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """拉取某个会话的历史消息（升序），用于前端恢复聊天上下文。"""
        self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        conv = self._conv_repo.get_conversation(conversation_id)
        if (
            conv is None
            or conv["user_id"] != self._user_id
            or conv["application_id"] != application_id
            or conv["tenant_id"] != self._tenant_id
        ):
            raise NotFoundError("会话不存在或无权访问")

        rows = self._msg_repo.list_messages_by_conversation(
            conversation_id, limit=limit,
        )
        result: list[dict[str, Any]] = []
        for r in rows:
            if r.get("role") not in ("user", "assistant"):
                continue
            tool_calls = r.get("tool_calls")
            if isinstance(tool_calls, str):
                try:
                    tool_calls = json.loads(tool_calls or "[]")
                except json.JSONDecodeError:
                    tool_calls = []
            result.append({
                "message_id": str(r["id"]),
                "role": r["role"],
                "content": r.get("content") or "",
                "tool_calls": tool_calls or [],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
        return result

    # ========== workflow 非流式运行 ==========
    async def run_workflow(
        self,
        application_id: UUID,
        inputs: dict[str, Any],
        thread_id: str | None,
        conversation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """走 GraphRunner 跑 dag 工作流；人审中断时返回 waiting_approval。"""
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        if app_card.get("flow_type") in ("chatflow", "agent"):
            raise ValidationError("对话流/智能体应用请使用对应的对话运行接口")

        canvas_json = await self._app_service.get_runtime_graph(application_id, self._tenant_id)
        if any(str(node.get("type")) == "18" for node in canvas_json.get("nodes") or []):
            raise ValidationError("工作流中暂不支持问答节点：该节点会中断且没有恢复通道，请改用对话流")

        runner = await self._runner_factory(
            self._app_service,
            self._uow,
            self._context,
            tenant_id=self._tenant_id,
            application_id=application_id,
            thread_id=thread_id,
            current_user_id=self._user_id,
            actor_username=getattr(self._principal, "username", None),
            conversation_id=conversation_id,
        )

        from internal.domain.graph.runtime import GraphInterrupted

        try:
            output = await runner.invoke(inputs)
            self._uow.commit()
            return {
                "status": "success",
                "output": output,
                "thread_id": runner.thread_id,
                "run_id": runner.run_id,
            }
        except GraphInterrupted as exc:
            self._uow.commit()
            return {
                "status": "waiting_approval",
                "thread_id": runner.thread_id,
                "run_id": runner.run_id,
                "approval": exc.interrupt_payload,
            }

    # ========== 统一对话入口（0074 PRD M3 端点收敛）==========
    def resolve_conversation_channel(self, application_id: UUID) -> dict:
        """统一 SSE 入口的路由分派依据：返回应用卡片（含 flow_type）。

        路由层按 flow_type 选择管线：chatflow → run_chatflow_stream；
        其余（agent / 旧 workflow 型聊天应用）→ run_agent_stream 三通道。
        可见性校验在此完成，流内重复校验由两条管线各自兜底。
        """
        return self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )

    def prepare_chat_run(
        self,
        application_id: UUID,
        *,
        message: str,
        conversation_id: UUID | None,
        resume: dict[str, Any] | None,
    ) -> None:
        """chat 通道请求级预检（与 prepare_chatflow_run 同级的 4xx 语义）。

        F10 续跑参数在此收口：resume 必须带 conversation_id 与 approved 布尔；
        "是否存在可恢复的挂起审批"依赖线程定位，留在流内校验。
        """
        normalized = (message or "").strip()
        if not normalized and resume is None:
            raise ValidationError("message 与 resume 至少提供一个")
        if resume is not None:
            if conversation_id is None:
                raise ValidationError("续跑必须提供 conversation_id")
            if not isinstance(resume, dict) or "approved" not in resume:
                raise ValidationError("resume 需提供 approved 布尔字段")

    # ========== 对话流流式运行 ==========
    def assert_chatflow_application(self, application_id: UUID) -> dict:
        """HTTP 层先行校验应用类型，避免把 422 包进 SSE 流。"""
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        if app_card.get("flow_type") != "chatflow":
            raise ValidationError("当前应用不是对话流，请使用工作流运行接口")
        return app_card

    def prepare_chatflow_run(
        self,
        application_id: UUID,
        *,
        message: str,
        conversation_id: UUID | None,
        resume: dict[str, Any] | None,
        thread_id: str | None,
    ) -> ChatflowPreparedRun:
        """请求级预检：应用类型、参数组合、会话归属、线程归属。

        必须在返回 StreamingResponse 之前调用，保证鉴权/参数错误以 JSON 4xx 返回，
        而不是在 SSE 流里推一条 error 事件。
        """
        self.assert_chatflow_application(application_id)

        normalized = (message or "").strip()
        if not normalized and resume is None:
            raise ValidationError("message 与 resume 至少提供一个")
        if resume is not None and conversation_id is None:
            raise ValidationError("续跑必须提供 conversation_id")

        if conversation_id is not None:
            conv = self._conv_repo.get_conversation(conversation_id)
            if (
                conv is None
                or conv["user_id"] != self._user_id
                or conv["application_id"] != application_id
                or conv["tenant_id"] != self._tenant_id
            ):
                raise NotFoundError("会话不存在或无权访问")
            cid = conversation_id
            conv_title = str(conv.get("title") or "")
        else:
            conv_title = normalized[:30] or "新对话"
            cid = self._conv_repo.insert_conversation(
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                title=conv_title,
            )

        bound_thread_id = self._bind_chatflow_thread_id(cid, thread_id)
        return ChatflowPreparedRun(
            application_id=application_id,
            message=normalized,
            conversation_id=cid,
            conversation_title=conv_title,
            thread_id=bound_thread_id,
            resume=resume,
        )

    async def run_chatflow_stream(
        self,
        prepared: ChatflowPreparedRun,
        inputs: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """跑一轮对话流并产出 SSE 事件。

        调用前必须已完成 prepare_chatflow_run；本方法只做运行与落库。
        与工作流 run 的区别：
        - 每轮以用户消息驱动，START 注入 USER_INPUT/CONVERSATION_NAME/CONVERSATION_ID
        - 输出节点的 output_message、问答节点的 question 直接作为聊天事件推送
        - 用户消息、中间输出、最终回答落库到 conversation/message
        """
        application_id = prepared.application_id
        message = prepared.message
        cid = prepared.conversation_id
        conv_title = prepared.conversation_title
        resume = prepared.resume

        from internal.domain.graph.runtime import GraphInterrupted

        bound_thread_id = prepared.thread_id
        run_repo = self._run_repo

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def emitter(event_type: str, payload: dict[str, Any]) -> None:
            await queue.put(("event", (event_type, payload)))

        async def make_runner(thread_id: str, run_id: UUID | None = None) -> Any:
            return await self._runner_factory(
                self._app_service,
                self._uow,
                self._context,
                tenant_id=self._tenant_id,
                application_id=application_id,
                thread_id=thread_id,
                run_id=run_id,
                current_user_id=self._user_id,
                actor_username=getattr(self._principal, "username", None),
                conversation_id=cid,
                on_node_event=emitter,
            )

        # 续跑复用上一轮中断的 run_id：既保证审计字段连续，
        # 也避免 message.run_id 外键指向不存在的 run 记录。
        resume_run_id: UUID | None = None
        if resume is not None:
            running = run_repo.get_running_by_thread(
                self._tenant_id, application_id, bound_thread_id,
            )
            if running is not None:
                resume_run_id = running["id"]
        runner = await make_runner(bound_thread_id, run_id=resume_run_id)

        # 上一轮停在提问中断、用户未回答就直接发新消息：放弃旧中断，
        # 换一个子线程重新 invoke，避免整条会话永久卡在 interrupt。
        if resume is None and message:
            history = await runner.list_state_history(limit=1)
            if history and history[0].get("interrupts"):
                bound_thread_id = f"{cid}:{uuid4()}"
                runner = await make_runner(bound_thread_id)

        start_inputs: dict[str, Any] = {
            **(inputs or {}),
            "USER_INPUT": message,
            "CONVERSATION_NAME": conv_title,
            "CONVERSATION_ID": str(cid),
        }

        # 用户消息先落库；先确保 run 记录存在，满足 message.run_id 外键。
        runner.ensure_run(start_inputs if resume is None else {"resume": resume})
        user_text = message or _resume_answer_text(resume)
        if user_text:
            self._msg_repo.append_message(
                conversation_id=cid,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                role="user",
                content=user_text,
                run_id=runner.run_id,
            )

        async def run_task() -> None:
            try:
                if resume is not None:
                    output = await runner.resume(resume)
                else:
                    output = await runner.invoke(start_inputs)
                queue.put_nowait(("output", output))
            except GraphInterrupted as exc:
                queue.put_nowait(("interrupted", exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("对话流运行失败 application=%s", application_id)
                queue.put_nowait(("error", exc))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(run_task())
        yield "run_start", {
            "conversation_id": str(cid),
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
        }

        output: Any = None
        interrupted: GraphInterrupted | None = None
        emitted_outputs: list[str] = []

        try:
            while True:
                kind, payload = await queue.get()
                if kind == "done":
                    break
                if kind == "event":
                    event_type, data = payload
                    if event_type == "output_message":
                        emitted_outputs.append(str((data or {}).get("content") or ""))
                    yield event_type, data
                elif kind == "output":
                    output = payload
                elif kind == "interrupted":
                    interrupted = payload
                elif kind == "error":
                    yield "error", {"message": str(payload), "code": "chatflow_failed"}
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if interrupted is not None:
            await self._handle_chatflow_interrupt(cid, interrupted, runner)
            self._conv_repo.touch(cid)
            payload = interrupted.interrupt_payload or {}
            if payload.get("type") == "question":
                self._uow.commit()
                yield "question", {
                    "node_id": payload.get("node_id"),
                    "question": payload.get("question") or "",
                    "options": payload.get("options") or [],
                    "conversation_id": str(cid),
                    "thread_id": interrupted.thread_id,
                    "run_id": str(runner.run_id),
                }
            else:
                self._uow.commit()
                yield "interrupted", {
                    "approval": payload,
                    "conversation_id": str(cid),
                    "thread_id": interrupted.thread_id,
                    "run_id": str(runner.run_id),
                }
            yield "final", {}
            return

        final_text = _extract_final_text(output)
        if final_text and final_text not in emitted_outputs:
            self._msg_repo.append_message(
                conversation_id=cid,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                role="assistant",
                content=final_text,
                run_id=runner.run_id,
            )
        self._conv_repo.touch(cid)
        self._uow.commit()

        yield "result", {
            "conversation_id": str(cid),
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
            "content": final_text,
            "output": output,
        }
        yield "final", {}

    def _bind_chatflow_thread_id(
        self,
        conversation_id: UUID,
        thread_id: str | None,
    ) -> str:
        """把客户端 thread_id 绑定到当前会话，阻断跨会话读取 checkpoint。

        允许三种形式：空（默认会话 ID）、纯会话 ID、`<tenant_id>:<business>` 包装前缀；
        business 必须是会话 ID 或以 `<conversation_id>:` 开头的子线程。
        """
        cid = str(conversation_id)
        raw = (thread_id or "").strip()
        if not raw:
            return cid

        tenant_prefix = f"{self._tenant_id}:"
        if raw.startswith(tenant_prefix):
            business = raw[len(tenant_prefix):]
        elif raw == cid or raw.startswith(f"{cid}:"):
            business = raw
        else:
            raise ForbiddenError("thread_id 不属于当前会话")

        if business != cid and not business.startswith(f"{cid}:"):
            raise ForbiddenError("thread_id 不属于当前会话")
        return business

    async def _handle_chatflow_interrupt(
        self,
        conversation_id: UUID,
        interrupted: Any,
        runner: Any,
    ) -> None:
        """中断时把问题落库，保证用户回答后历史仍能还原。"""
        payload = interrupted.interrupt_payload or {}
        if payload.get("type") != "question":
            return
        question = str(payload.get("question") or "").strip()
        if not question:
            return
        self._msg_repo.append_message(
            conversation_id=conversation_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=runner.application_id,
            role="assistant",
            content=question,
            run_id=runner.run_id,
            metadata={
                "type": "question",
                "node_id": payload.get("node_id"),
                "options": payload.get("options") or [],
                "thread_id": interrupted.thread_id,
            },
        )

    # ========== 内部：tools ==========
    def _legacy_tool_specs(self, tool_resource_ids: list[Any]) -> list[LLMToolSpec]:
        """兼容旧配置：把 tool_resource_ids 解析为资源后转成 tools 形态再解析。

        20260731 双轨合并保留；画布统一写 coze tools 键后（计划 P3 完成时）删除。
        """
        raw: list[dict[str, Any]] = []
        for rid_value in tool_resource_ids or []:
            try:
                rid = UUID(str(rid_value))
            except (ValueError, TypeError):
                continue
            record = self._resource_service.resolve_for_tenant(rid, self._tenant_id)
            if record is None:
                continue
            cfg = record.get("config") or {}
            name = record.get("name") or cfg.get("tool_name")
            if not name:
                # 20261106 review 修正：执行器按租户工具目录 name 索引查找，编造的
                # tool_{hex} 兜底名必然查不到，只会产生"模型可见但执行必失败"的假声明，
                # 空名资源直接跳过并不再暴露给模型
                logger.warning("legacy 工具资源缺少名称，跳过 rid=%s", rid)
                continue
            raw.append({
                "name": name,
                "description": record.get("description") or cfg.get("description") or "",
                "parameters": cfg.get("parameters") or {"type": "object", "properties": {}},
            })
        return build_tool_specs(raw)
