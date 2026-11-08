"""Agent 循环节点（coze agent_loop，本项目 type_code=100）。

独立图协议：plan / execute / reflect 三阶段，非 Dag 节点。

config 约定：
- modleName: 主模型 ID（同 LLM 节点）
- systemPrompt: 系统提示词（agent 角色）
- tools: 向 LLM 暴露的工具 schema（OpenAI tools 数组）；同时构成执行白名单，
  模型调用未声明工具时拒绝执行（见 react.run_react_loop）
- maxToolRounds: execute 阶段 ReAct 最大轮次（默认 5）
- maxReflectRounds: reflect 最大迭代轮次（默认 3，防止 plan→reflect 死循环）
- plannerPrompt: 可选，plan 阶段系统提示词（默认内置）
- reflectorPrompt: 可选，reflect 阶段系统提示词（默认内置）
- datasets: 知识库列表（0074 PRD F5 知识库即工具），项为
  {datasetId, name?, description?, mode: "onDemand"|"always", topK?}；
  onDemand 项合成 knowledge_search_N 检索工具（N=配置序，进白名单），
  always 项在执行前检索一次并注入 system 参考资料段
- mcpServers: MCP server 快照列表（0074 PRD F6），项为
  {serverUrl, name?, headers?, enabledTools: [{name, description, inputSchema}]}；
  勾选项直接合成同名工具（运行时不再 discover，快照失效即跳过）
- workflows: 工作流即工具挂载（0074 PRD F7），项为
  {applicationId, name?, description?}；按配置序合成 workflow_N 工具，
  schema 来自目标 start 节点启动参数，执行经 services["workflow_tool"]
- subAgents: 智能体协作挂载（M4 PRD F14.1），项为
  {applicationId, mode: "delegate"|"handoff", toolName?, description?}；
  delegate 项合成 agent_{slug} 委派工具（固定 question 入参），执行经
  services["agent_tool"]；handoff 项合成同名声明性工具（不进执行器分派），
  模型调用即整轮短路并经 outputs.handoff 透出接管语义（M4 PRD F14.9，T-c6）
- memory: 短期记忆配置（0074 PRD F8）。user 端 chat 通道由 ChatService 依据
  本配置拉取会话历史并经 history 入参注入；画布试运行/工作流编排本期不自动拉历史
- sensitiveTools: 需人工审批的工具声明（0074 PRD F10），项为
  {name} 或裸字符串；命中敏感工具的轮次整轮挂起等待批准（见下 F10 流程）
- visionEnabled: 视觉开关（0074 PRD F9）。仅当运行入参携带 images 且本开关为
  true 时，把当前 user 消息组装为多模态 content parts；否则忽略图片
- qualityGate: 运行时质量门（M4 PRD F19.2），{enabled, judgeModel?, rubric?,
  passScore?, maxRegen?}。节点收敛产出终稿后调 judge 内核打分（score>=passScore
  为过，阈值判定在本消费方，不信内核 payload.passed）；不达标且重生未超
  maxRegen → critique 作 user 消息追加后再跑一次 execute（judge 与重生消耗均
  计入本 run usage/tokenBudget）；达上限仍不过或 judge 异常 → fail-open 放行
  （U13 裁决）；终判经 outputs.judge 与 trace "judge" 事件 additive 透出。
  审批挂起轮/接管轮/预算触顶轮/空答案轮/子 run（workflow_chain 非空，C8）跳过

运行期入参（ctx.eval_context.input，20261106 P3 chat 兼容通道专用；
画布试运行/工作流不携带这些键，行为与改造前一致）：
- react_only: 跳过 plan/reflect，只跑一轮 execute（对齐旧 chat SSE 通道的调用成本与语义）
- history: 多轮消息 [{role, content}, ...]，拼在 system 与当前问题之间
- context: AgentRunContext 的 to_storage_dict 平铺形态（画布入参需 JSONB 可
  序列化，20261106 review 修正），节点内还原后透传给 LLM 请求（租户 header
  与 chat 旧通道一致）；已是 AgentRunContext 实例时原样使用
- max_tool_rounds: 覆盖 config.maxToolRounds（chat 通道沿用旧默认 10）
- workflow_chain: 工具调用祖先链（applicationId 字符串列表，0074 PRD F7.2；
  M4-c F14.2 语义泛化：workflow 与 agent 挂载共用此链与深度/去环预算，
  历史键名保留不动以兼容既有画布入参）；顶层调用不携带，链随子 run 入参逐层下传
- images: 图片 URL 列表（0074 PRD F9，chat 通道随消息携带），受
  config.visionEnabled 门控
- approval_resume: 0074 PRD F10 审批续跑入参
  {approved: bool, comment: str, snapshot: {...}}；snapshot 为本节点上次挂起时
  经 outputs 透出的执行现场（messages/plan_tasks/reflect_round/reflect_history/
  usage），节点据此跳过 PLAN 与 always 库检索、还原消息后从待答轮继续执行
- handoff_inbound: M4 PRD F14.9 接管目标侧入参 {from_application_id: 会话归属
  应用 ID}（ChatService 在接管路由轮写入）；存在时自动注入 hand_back 归位声明
  工具，模型调用即短路并透出 returned=true 的 handoff 输出

F10 挂起流程：execute 的某轮 tool_calls 命中 sensitiveTools 且调用 ID 未经批准
时，内核不执行该轮任何工具，节点提前返回
outputs={"awaiting_approval": True, "approval": {type/iteration/待答调用},
 "snapshot": {执行现场}}；消费方（ChatService）保存快照置 run 为 interrupted，
用户裁决后经 approval_resume 重新 invoke 本图续跑（快照里没有 langgraph 挂起
中断，R6 断连清理语义不受影响）。

F14.9 接管流程：execute 任一轮调用 handoff 声明工具（或目标侧 hand_back）时，
内核整轮短路（同轮其余工具也不执行、正文不作最终回答），节点透出
outputs={"handoff": {tool_name/tool_call_id/application_id/returned/...},
"finish_reason": "handed_off"|"handed_back"}（复用预算的 outputs 覆盖通道，
JSONB 可序列化）；消费方（ChatService）据此切换或归位会话路由态。深度模式下
命中同样短路整个 reflect 循环，不再支付评审成本。

协议流程：
1. PLAN：LLM 把用户 query 拆解成结构化任务列表 JSON：
   {"tasks": [{"id": "...", "goal": "...", "acceptance": "..."}, ...]}
2. EXECUTE：对整批 tasks 跑一次 ReAct 循环（用户 query + 已知任务清单作 system），
   工具执行结果 + LLM 最终 answer 作为 execute 输出。
3. REFLECT：LLM 根据 execute 产出判定是否达标：
   {"done": true/false, "critique": "...", "missing": "..."}
   若 done=false 且未达 maxReflectRounds：把 critique 追加进 messages 回到 execute。
   若 done=true 或轮次耗尽：返回最终 answer。

依赖：
- ctx.services.get("llm")：LLMClient（async chat(messages, tools, ...) -> LLMResponse）
- ctx.services.get("tool_executor")：可选，async (name, args) -> str
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import time
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from internal.domain.agent.judge import judge
from internal.domain.agent.mcp_client import (
    DEFAULT_TIMEOUT_SECONDS,
    McpClientError,
    McpSession,
)
from internal.domain.agent.mcp_governance import get_mcp_breaker, get_mcp_limiter
from internal.domain.agent.mcp_observer import (
    MCP_STATUS_OK,
    MCP_STATUS_REJECTED,
    MCP_STATUS_TOOL_ERROR,
    MCP_STATUS_TRANSPORT_ERROR,
    McpCallRecord,
    mcp_observer,
)
from internal.domain.agent.mcp_session_pool import McpSessionPool, get_mcp_session_pool
from internal.domain.agent.memory import render_memory_block, render_summary_block
from internal.domain.agent.react import (
    BUDGET_EXCEEDED_REASON,
    HANDED_BACK_REASON,
    HANDED_OFF_REASON,
    accumulate_usage,
    build_tool_specs,
    run_react_loop,
)
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.canvas.agent_config import (
    AGENT_TOOL_NAME_PREFIX,
    DATASET_MODES,
    DEFAULT_MCP_SESSION_SCOPE,
    DEFAULT_SUB_AGENT_MODE,
    KNOWLEDGE_TOOL_NAME_PREFIX,
    MAX_SUB_AGENTS,
    MCP_SESSION_SCOPES,
    QUALITY_GATE_DEFAULT_MAX_REGEN,
    QUALITY_GATE_DEFAULT_PASS_SCORE,
    QUALITY_GATE_MAX_MAX_REGEN,
    QUALITY_GATE_MAX_PASS_SCORE,
    QUALITY_GATE_MIN_MAX_REGEN,
    QUALITY_GATE_MIN_PASS_SCORE,
    SUB_AGENT_MODES,
    WORKFLOW_TOOL_NAME_PREFIX,
)
from internal.domain.canvas.node_type import NodeType
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.errors import ValidationError
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.llm.client import LLMToolSpec
from internal.domain.llm.multimodal import build_multimodal_content, normalize_image_urls
from internal.domain.security.ssrf_guard import validate_outbound_url

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_ROUNDS = 5
DEFAULT_MAX_REFLECT_ROUNDS = 3

# M4 PRD F14.9：接管目标侧自动注入的归位声明工具名（不进执行器，内核门控短路）
HAND_BACK_TOOL_NAME = "hand_back"

# M4-d PRD F19.2：judge 参考资料体量护栏——只保留最近 N 条工具观察项、
# 单条截断 M 字，防长工具链把评审 prompt 撑爆（阈值判定语义不受影响）
GATE_MAX_OBSERVATIONS = 5
GATE_OBSERVATION_TRIM = 1000

# execute 阶段 LLM 异常桩前缀（与 _execute 异常分支文案同源）：质量门重生时
# 见到它视同重生失败，不得当作新答案顶掉原稿（批末 review P1-2）
EXECUTE_ERROR_PREFIX = "[execute error]"

# 0074 PRD F5 知识库即工具：前缀/模式枚举复用配置面定义，防止两处口径漂移
DEFAULT_KNOWLEDGE_TOP_K = 5
# 检索 observation 截断长度：与 DATASET 节点返回体量相仿，防 chunks 挤占 ReAct 上下文
KNOWLEDGE_OBSERVATION_LIMIT = 4096
KNOWLEDGE_EMPTY_MESSAGE = "（知识库中未检索到相关内容）"

DEFAULT_PLANNER_PROMPT = (
    "你是任务规划器。把用户目标拆解为 1~5 个可执行的子任务。"
    '输出 JSON：{"tasks": [{"id": "t1", "goal": "...", "acceptance": "..."}]}。'
    "不要输出 JSON 以外的任何字符。"
)

DEFAULT_REFLECTOR_PROMPT = (
    "你是质量评审。根据原始目标和执行结果判断是否已经完成："
    '输出 JSON：{"done": true/false, "critique": "简短问题描述", "suggestion": "下一步建议"}。'
    "不要输出 JSON 以外的任何字符。"
)


def _parse_sensitive_tool_names(raw: Any) -> set[str]:
    """0074 PRD F10：sensitiveTools 配置容错解析（[{name}] 或裸字符串混合均可）。"""
    if not isinstance(raw, list):
        return set()
    names: set[str] = set()
    for item in raw:
        name = str((item or {}).get("name") if isinstance(item, dict) else item or "").strip()
        if name:
            names.add(name)
    return names


def _pending_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    """0074 PRD F10：取快照末尾 assistant(tool_calls) 的调用 ID 集合。

    审批 ID 必须由节点从执行现场推导，不信任恢复入参自带清单，
    防止伪造 approved 集合绕过敏感工具门控。
    """
    if not messages:
        return set()
    last = messages[-1]
    if str(last.get("role") or "") != "assistant":
        return set()
    return {
        str(item.get("id"))
        for item in last.get("tool_calls") or []
        if isinstance(item, dict) and item.get("id")
    }


def _parse_approval_resume(raw: Any) -> dict[str, Any] | None:
    """0074 PRD F10：校验并归一化 approval_resume 入参；非法返回 None（按新 run 处理）。"""
    if not isinstance(raw, dict):
        return None
    snapshot = raw.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    messages_raw = snapshot.get("messages")
    if not isinstance(messages_raw, list):
        return None
    messages = [m for m in messages_raw if isinstance(m, dict)]
    if not messages:
        return None
    usage = snapshot.get("usage") if isinstance(snapshot.get("usage"), dict) else {}
    return {
        "approved": bool(raw.get("approved")),
        "comment": str(raw.get("comment") or ""),
        "messages": messages,
        "plan_tasks": [t for t in snapshot.get("plan_tasks") or [] if isinstance(t, dict)],
        "reflect_round": _to_int(snapshot.get("reflect_round")) or 0,
        "reflect_history": [
            h for h in snapshot.get("reflect_history") or [] if isinstance(h, dict)
        ],
        "usage": usage,
    }


def _gate_int(value: Any, min_value: int, max_value: int, default: int) -> int:
    """质量门数值容错：非严格整数或越界一律回配置面默认（与 agent_config 同口径）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if not min_value <= value <= max_value:
        return default
    return value


def _parse_quality_gate(raw: Any) -> dict[str, Any]:
    """M4 PRD F19.2：运行侧容错解析 qualityGate（历史图/脏值不抛错，界值复用配置面常量）。"""
    gate = raw if isinstance(raw, dict) else {}
    judge_model = gate.get("judgeModel")
    rubric = gate.get("rubric")
    return {
        "enabled": bool(gate.get("enabled")),
        "judgeModel": str(judge_model) if isinstance(judge_model, str) else "",
        "rubric": str(rubric) if isinstance(rubric, str) else "",
        "passScore": _gate_int(
            gate.get("passScore"),
            QUALITY_GATE_MIN_PASS_SCORE,
            QUALITY_GATE_MAX_PASS_SCORE,
            QUALITY_GATE_DEFAULT_PASS_SCORE,
        ),
        "maxRegen": _gate_int(
            gate.get("maxRegen"),
            QUALITY_GATE_MIN_MAX_REGEN,
            QUALITY_GATE_MAX_MAX_REGEN,
            QUALITY_GATE_DEFAULT_MAX_REGEN,
        ),
    }


def _bind_judge_llm(llm: Any, model_id: str) -> Any:
    """为 judge 内核绑定显式模型 ID。

    judge() 调 chat 不传 model（F19.1 三消费方同源），而画布通道的
    LLMServiceAdapter 必须按 model 解析客户端；探测 chat 签名含 model 参数时
    用 partial 绑定，裸 LLMClient（模型已 bake、无该参数）原样透传。
    """
    if not model_id:
        return llm
    try:
        params = inspect.signature(llm.chat).parameters
    except (TypeError, ValueError):
        return llm
    if "model" not in params:
        return llm
    return types.SimpleNamespace(chat=functools.partial(llm.chat, model=model_id))


@dataclass
class _GateState:
    """质量门可变态：judge/重生过程中被门方法就地更新的执行现场。"""

    answer: str
    messages: list[dict[str, Any]]
    observations: list[str]
    reflect_round: int = 0
    awaiting: dict[str, Any] | None = None
    handoff: dict[str, Any] | None = None
    budget_hit: bool = False


@dataclass
class _GateContext:
    """质量门依赖打包（避免 _apply_quality_gate 参数爆炸，编码规则 ≤6 参数）。"""

    gate: dict[str, Any]
    state: _GateState
    llm: Any
    model_id: str
    question: str
    usage_total: dict[str, int]
    token_budget: int | None
    emit: Any
    do_execute: Callable[[int], Awaitable[dict[str, Any]]]


class AgentLoopNodeHandler(NodeHandler):
    """plan/execute/reflect 三阶段 Agent 循环节点。"""

    type_name = NodeType.AGENT_LOOP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}
        # 20261106 P3 服务端兼容契约：chat 入口以 graph 入参额外携带
        # react_only（跳过 plan/reflect，仅跑 ReAct）与 history（多轮消息）。
        # 画布试运行/工作流不传这两个键，行为与改造前完全一致。
        runtime_input: dict[str, Any] = {}
        if ctx.eval_context is not None and isinstance(ctx.eval_context.input, dict):
            runtime_input = ctx.eval_context.input
        react_only = bool(runtime_input.get("react_only"))
        history_raw = runtime_input.get("history")
        history = (
            [h for h in history_raw if isinstance(h, dict)] if isinstance(history_raw, list) else []
        )
        # M4 PRD F15.5：chat 通道透传的更早对话摘要（画布试运行/工作流不传即为空）
        summary = str(runtime_input.get("summary") or "")
        # M4 PRD F16.4：chat 通道召回注入的长期记忆正文列表（防御式过滤非字符串项）
        memories_raw = runtime_input.get("memories")
        memories = (
            [str(item) for item in memories_raw if str(item).strip()]
            if isinstance(memories_raw, list)
            else []
        )
        chat_context = _resolve_run_context(runtime_input.get("context"))
        user_input = str(
            ctx.inputs.get("input")
            or runtime_input.get("input")
            or runtime_input.get("USER_INPUT")
            or ""
        )

        model_id = _to_str(config.get("modleName") or config.get("modelName"))
        system_prompt = _to_str(config.get("systemPrompt"))
        planner_prompt = _to_str(config.get("plannerPrompt")) or DEFAULT_PLANNER_PROMPT
        reflector_prompt = _to_str(config.get("reflectorPrompt")) or DEFAULT_REFLECTOR_PROMPT
        max_tool_rounds = (
            _to_int(runtime_input.get("max_tool_rounds"))
            or _to_int(config.get("maxToolRounds"))
            or DEFAULT_MAX_TOOL_ROUNDS
        )
        max_reflect_rounds = _to_int(config.get("maxReflectRounds")) or DEFAULT_MAX_REFLECT_ROUNDS
        # 0074 PRD F11.1：单 run token 预算（缺省/非法 = 不限制）
        token_budget = _to_int(config.get("tokenBudget"))
        # M4-d PRD F19.2：运行时质量门（缺省/脏值 = 关闭，界值与配置面同源）
        quality_gate = _parse_quality_gate(config.get("qualityGate"))
        # 0074 PRD F10：敏感工具名单（空集 = 不启用人审门控）
        sensitive_names = _parse_sensitive_tool_names(config.get("sensitiveTools"))
        # 0074 PRD F9：图片入参受节点视觉开关门控，未开启直接忽略
        images = (
            normalize_image_urls(runtime_input.get("images"))
            if bool(config.get("visionEnabled"))
            else []
        )
        # 0074 PRD F10：审批续跑入参（非法/缺失按全新 run 走）
        resume = _parse_approval_resume(runtime_input.get("approval_resume"))

        tool_specs = build_tool_specs(config.get("tools"))
        tool_executor = (
            ctx.services.get("tool_executor") if ctx.services.has("tool_executor") else None
        )

        # 0074 知识库即工具（PRD F5.1）：onDemand 库按配置序合成 knowledge_search_N
        # 检索工具（N 从 1 起，含 always 库占位，保证名称与配置序一致稳定）。
        dataset_entries = _parse_dataset_entries(config.get("datasets"))
        search_map: dict[str, dict[str, Any]] = {}
        # 0074 PRD F5.3 引用溯源：检索命中的 chunk 元信息经侧信道带回 trace
        # （内核执行器契约只回传 observation 文本；同名工具在轮内串行执行，
        # 消费侧在 tool_end 事件按工具名 pop，不存在竞态）
        knowledge_chunks: dict[str, list[dict[str, Any]]] = {}
        for index, entry in enumerate(dataset_entries, start=1):
            if entry["mode"] != "onDemand":
                continue
            tool_name = f"{KNOWLEDGE_TOOL_NAME_PREFIX}{index}"
            search_map[tool_name] = entry
            tool_specs.append(
                LLMToolSpec(
                    name=tool_name,
                    description=_knowledge_tool_description(entry),
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "检索关键词或完整问题"},
                        },
                        "required": ["query"],
                    },
                )
            )
        # 0074 PRD F6：MCP 快照展开——配置保存时已 discover 并勾选，运行时只按
        # 快照合成同名工具（server 暂不可用不影响清单；重名/保留前缀项跳过并告警）。
        mcp_map: dict[str, dict[str, Any]] = {}
        existing_names = {spec.name for spec in tool_specs}
        # M4-b F17.2/F17.4：会话复用两档——缺省 run 级按 (url, headers) 指纹去重
        # 建 McpSession（同一 server 的多工具共享一次握手，节点出口 finally 全关，
        # 审批挂起期间不持连，续跑按新 run 重新建连）；scope=conversation 且存在
        # 会话 ID 时改用进程级会话池（跨 run 复用，池内负责 TTL/LRU 驱逐与关闭）。
        # 两档对象构造均不发起 IO（连接惰性建立）。
        mcp_sessions: dict[tuple[str, tuple[tuple[str, str], ...]], McpSession] = {}
        mcp_pool: McpSessionPool | None = None
        conversation_id = str(ctx.env.conversation_id or "")
        mcp_tenant = _mcp_tenant_label(ctx.env.tenant_id)
        mcp_scope = _parse_mcp_session_scope(config.get("mcpSession"))
        if mcp_scope == "conversation":
            if conversation_id:
                mcp_pool = get_mcp_session_pool()
            else:
                # R13 前提缺失：无会话归属则池 key 无从隔离，安全回落 run 档
                logger.warning("mcpSession.scope=conversation 但缺少 conversation_id，回落 run 级")
        for server in _parse_mcp_entries(config.get("mcpServers")):
            fingerprint = _mcp_fingerprint(server["serverUrl"], server["headers"])
            if mcp_pool is None and fingerprint not in mcp_sessions:
                mcp_sessions[fingerprint] = McpSession(
                    server["serverUrl"], server["headers"], server["timeoutSeconds"]
                )
            for tool in server["enabledTools"]:
                tool_name = tool["name"]
                if tool_name in existing_names or _is_reserved_tool_name(tool_name):
                    logger.warning(
                        "MCP 工具与既有工具名冲突，跳过: %s server=%s",
                        tool_name,
                        server["serverUrl"],
                    )
                    continue
                existing_names.add(tool_name)
                tool_specs.append(
                    LLMToolSpec(
                        name=tool_name,
                        description=tool["description"] or f"MCP 工具 {tool_name}",
                        parameters=tool["inputSchema"] or {"type": "object", "properties": {}},
                    )
                )
                mcp_map[tool_name] = {
                    "serverUrl": server["serverUrl"],
                    "headers": server["headers"],
                    "timeoutSeconds": server["timeoutSeconds"],
                    "fingerprint": fingerprint,
                }

        # 0074 PRD F7：工作流即工具——按配置序合成 workflow_N（N 含跳过的不可用项，
        # 保证名称与配置序稳定一致）；describe 失败/不可见的挂载跳过，执行侧经
        # services["workflow_tool"]（应用层端口，duck-typing，不反向 import）。
        workflow_map: dict[str, str] = {}
        workflow_service = (
            ctx.services.get("workflow_tool") if ctx.services.has("workflow_tool") else None
        )
        workflow_chain = _parse_workflow_chain(runtime_input.get("workflow_chain"))
        for index, entry in enumerate(_parse_workflow_entries(config.get("workflows")), start=1):
            tool_name = f"{WORKFLOW_TOOL_NAME_PREFIX}{index}"
            if workflow_service is None:
                logger.warning(
                    "workflow_tool 服务未注册，跳过挂载 application=%s", entry["applicationId"]
                )
                continue
            try:
                described = await workflow_service.describe(entry["applicationId"], workflow_chain)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "工作流工具 describe 失败，跳过 application=%s: %s", entry["applicationId"], exc
                )
                continue
            if described is None:
                logger.warning(
                    "工作流工具挂载不可用（不存在/不可见/非工作流），跳过 application=%s",
                    entry["applicationId"],
                )
                continue
            tool_specs.append(
                LLMToolSpec(
                    name=tool_name,
                    description=_workflow_tool_description(entry, described),
                    parameters=described.get("parameters") or {"type": "object", "properties": {}},
                )
            )
            workflow_map[tool_name] = entry["applicationId"]
            # M4-c 起 agent 合成需要防撞名（workflow_N 按序不会自撞，登记供后续层比对）
            existing_names.add(tool_name)

        # M4-c PRD F14.2/F14.3/F14.9：智能体即工具——subAgents 挂载合成 agent_{slug} 工具；
        # 不可用挂载（不存在/不可见/未发布/非智能体）由 describe 返回 None 跳过。
        # 委派链与 workflow 共用 workflow_chain 祖先链（语义泛化为调用链，R15 预算共享）。
        # delegate 进执行器分派；handoff 只声明（命中由内核整轮短路，不进分派）。
        agent_map: dict[str, str] = {}
        handoff_map: dict[str, str] = {}
        delegation_lines: list[str] = []
        handoff_lines: list[str] = []
        agent_service = ctx.services.get("agent_tool") if ctx.services.has("agent_tool") else None
        self_app_id = str(ctx.env.application_id or "")
        for entry in _parse_sub_agent_entries(config.get("subAgents")):
            is_handoff = entry["mode"] == "handoff"
            if entry["applicationId"] == self_app_id:
                logger.warning("subAgents 自引用，跳过 application=%s", entry["applicationId"])
                continue
            if agent_service is None:
                logger.warning(
                    "agent_tool 服务未注册，跳过挂载 application=%s", entry["applicationId"]
                )
                continue
            try:
                described = await agent_service.describe(
                    entry["applicationId"],
                    workflow_chain,
                    tool_name=entry["toolName"] or None,
                    description=entry["description"] or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "智能体工具 describe 失败，跳过 application=%s: %s", entry["applicationId"], exc
                )
                continue
            if described is None:
                logger.warning(
                    "智能体工具挂载不可用（不存在/不可见/未发布/非智能体），跳过 application=%s",
                    entry["applicationId"],
                )
                continue
            agent_tool_name = str(described.get("name") or "")
            if not agent_tool_name or agent_tool_name in existing_names:
                logger.warning(
                    "智能体工具名缺失或与既有工具冲突，跳过: %s application=%s",
                    agent_tool_name,
                    entry["applicationId"],
                )
                continue
            existing_names.add(agent_tool_name)
            agent_parameters = described.get("parameters") or {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            }
            agent_description = str(described.get("description") or "")
            if is_handoff:
                agent_description = (
                    f"{agent_description}。调用后本会话后续对话由该专家接管（多轮直达），"
                    "直至用户或专家归位"
                )
            tool_specs.append(
                LLMToolSpec(
                    name=agent_tool_name,
                    description=agent_description,
                    parameters=agent_parameters,
                )
            )
            if is_handoff:
                handoff_map[agent_tool_name] = entry["applicationId"]
                handoff_lines.append(f"- {agent_tool_name}：{described.get('description') or ''}")
            else:
                agent_map[agent_tool_name] = entry["applicationId"]
                delegation_lines.append(
                    f"- {agent_tool_name}：{described.get('description') or ''}"
                )

        # M4 PRD F14.9：接管目标侧自动注入 hand_back 归位声明工具（ChatService 经
        # start_inputs 写 handoff_inbound）；命中由内核短路整轮，不进执行器分派。
        # 与既有工具撞名时跳过注入（不挂门控），保证用户工具语义不被劫持。
        hand_back_enabled = False
        handoff_inbound = runtime_input.get("handoff_inbound")
        inbound_from = (
            str(handoff_inbound.get("from_application_id") or "")
            if isinstance(handoff_inbound, dict)
            else ""
        )
        if inbound_from:
            if HAND_BACK_TOOL_NAME in existing_names:
                logger.warning("hand_back 声明工具与既有工具撞名，跳过归位注入")
            else:
                existing_names.add(HAND_BACK_TOOL_NAME)
                hand_back_enabled = True
                tool_specs.append(
                    LLMToolSpec(
                        name=HAND_BACK_TOOL_NAME,
                        description=_hand_back_tool_description(),
                        parameters={"type": "object", "properties": {}},
                    )
                )

        if search_map or mcp_map or workflow_map or agent_map:
            # 合成执行器链：知识库向量检索 → 工作流子 run → MCP 快照 → 租户目录
            # 基础执行器；未注册等异常交由 ReAct 内核转 [error] observation，
            # 不在此层吞掉。
            base_executor = tool_executor

            async def _execute_tool(name: str, arguments: dict[str, Any]) -> str:
                dataset_entry = search_map.get(name)
                if dataset_entry is not None:
                    observation, chunks_meta = await _knowledge_search_detail(
                        ctx, dataset_entry, _knowledge_query(arguments)
                    )
                    if chunks_meta:
                        knowledge_chunks[name] = chunks_meta
                    return observation
                application_id = workflow_map.get(name)
                if application_id is not None:
                    # 理论不可达（有挂载行必有服务），防御性兜底并收窄类型；
                    # 环/深度防护在应用层端口内做（RuntimeError → [error] observation）
                    if workflow_service is None:
                        return "[error] workflow_tool 服务未注册"
                    return await workflow_service.invoke(application_id, arguments, workflow_chain)
                mcp_entry = mcp_map.get(name)
                if mcp_entry is not None:
                    return await _execute_mcp_tool(
                        mcp_entry,
                        name,
                        arguments,
                        mcp_sessions,
                        pool=mcp_pool,
                        conversation_id=conversation_id,
                        tenant=mcp_tenant,
                    )
                agent_application_id = agent_map.get(name)
                if agent_application_id is not None:
                    # 理论不可达（有挂载行必有服务），防御性兜底；环/深度防护在应用层端口内
                    if agent_service is None:
                        return "[error] agent_tool 服务未注册"
                    return await agent_service.invoke(
                        agent_application_id, arguments, workflow_chain
                    )
                if base_executor is None:
                    raise LookupError(f"工具未注册: {name}")
                result = base_executor(name, arguments)
                if inspect.isawaitable(result):
                    result = await result
                return str(result)

            tool_executor = _execute_tool

        if not ctx.services.has("llm"):
            return NodeResult(
                outputs={
                    "output": f"[AgentLoop stub] model={model_id} input={user_input[:80]}",
                    "plan": [],
                    "iterations": 0,
                }
            )

        llm = ctx.services.get("llm")
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if resume:
            # F10 续跑：挂起前的消耗回填累计，token 预算跨"挂起-恢复"连续计账
            accumulate_usage(usage_total, resume["usage"])

        async def _emit(etype: str, payload: dict[str, Any]) -> None:
            if ctx.emit_event is None:
                return
            try:
                await ctx.emit_event(etype, {"node_id": ctx.node_id, **payload})
            except Exception:  # noqa: BLE001
                logger.exception("emit agent_loop trace event failed: %s", etype)

        # 1. PLAN（react_only：chat 兼容契约不需要计划事件，也不该多付一次 LLM 调用；
        #    F10 快照续跑：任务清单取自快照，不重做计划）
        if resume:
            plan_tasks = resume["plan_tasks"]
        elif react_only:
            plan_tasks = []
        else:
            plan_tasks = await self._plan(
                ctx, _emit, llm, planner_prompt, user_input, usage_total, model_id
            )

        # 2. EXECUTE / REFLECT 迭代（always 库执行前自动检索注入参考资料段，PRD F5.2）
        if resume:
            # F10 续跑：参考资料段已烘进快照 system 消息，不再重复检索/组装；
            # 快照 messages 末条即待答的 assistant(tool_calls)，由内核排空续跑
            execution_messages = resume["messages"]
            reflect_history = resume["reflect_history"]
        else:
            always_reference = await self._retrieve_always_reference(
                ctx, dataset_entries, user_input
            )
            execution_messages = self._build_execution_messages(
                # F14.5：委派语义提示词段随合成结果动态追加（无专家挂载则零改动）
                system_prompt=system_prompt
                + _delegation_prompt_section(delegation_lines, handoff_lines)
                + always_reference,
                user_input=user_input,
                plan_tasks=plan_tasks,
                history=history,
                images=images,
                summary=summary,
                memories=memories,
            )
            reflect_history = []
        final_answer = ""
        final_finish_reason = ""
        execute_budget_hit = False
        awaiting_info: dict[str, Any] | None = None
        awaiting_round = 0
        # M4 PRD F14.9：接管/归位命中信息（内核 handoff 事件 payload）
        handoff_info: dict[str, Any] | None = None

        # F10 审批裁决 → 待答轮调用 ID 集合：批准即放行快照里全部待答调用，
        # 拒绝即全部回灌拒绝 observation（整轮语义，与门控"整轮挂起"对称）
        approved_ids: set[str] = set()
        rejected_ids: set[str] = set()
        if resume:
            pending_ids = _pending_tool_call_ids(execution_messages)
            if resume["approved"]:
                approved_ids = pending_ids
            else:
                rejected_ids = pending_ids

        # LLM 扩展参数：画布经 LLMServiceAdapter 必须按 model 解析 client；
        # context 为 chat 兼容通道透传的 AgentRunContext（租户 header）。
        execute_chat_kwargs: dict[str, Any] = {}
        if model_id:
            execute_chat_kwargs["model"] = model_id
        if chat_context is not None:
            execute_chat_kwargs["context"] = chat_context

        async def _do_execute(reflect_round: int) -> dict[str, Any]:
            # F11.1：预算判定基于本 run 已累计的 usage（plan 阶段、历次 execute/reflect），
            # 因此把 usage_total 当前值作为基线传进内核
            return await self._execute(
                ctx=ctx,
                emit=_emit,
                llm=llm,
                tool_specs=tool_specs,
                tool_executor=tool_executor,
                messages=execution_messages,
                model_id=model_id,
                max_tool_rounds=max_tool_rounds,
                usage_total=usage_total,
                reflect_round=reflect_round,
                chat_kwargs=execute_chat_kwargs,
                knowledge_chunks=knowledge_chunks,
                token_budget=token_budget,
                react_approval={
                    "sensitive_tool_names": sensitive_names,
                    "approved_call_ids": approved_ids,
                    "rejected_call_ids": rejected_ids,
                    "rejection_comment": resume["comment"] if resume else "",
                },
                # M4 PRD F14.9：接管声明门控（命中整轮短路，见 react.run_react_loop）
                react_handoff={
                    "handoff_targets": handoff_map,
                    "hand_back_name": HAND_BACK_TOOL_NAME if hand_back_enabled else None,
                },
            )

        # M4-d F19.2：质量门入参现场（终稿观察项/最近轮次，供 judge 参考资料与重生 trace）
        last_round = 0
        last_observations: list[str] = []
        try:
            if react_only:
                execute_result = await _do_execute(0)
                awaiting_info = execute_result["awaiting"]
                handoff_info = execute_result["handoff"]
                last_observations = list(execute_result.get("observations") or [])
                if awaiting_info is None and handoff_info is None:
                    final_answer = execute_result["content"]
                    execute_budget_hit = execute_result["budget_hit"]
            else:
                # F10 续跑：深度模式从快照记录的 reflect_round 接着转，不复跑已完成的轮
                for reflect_round in range(
                    (resume["reflect_round"] if resume else 0), max_reflect_rounds
                ):
                    execute_result = await _do_execute(reflect_round)
                    last_round = reflect_round
                    last_observations = list(execute_result.get("observations") or [])
                    awaiting_info = execute_result["awaiting"]
                    if awaiting_info is not None:
                        awaiting_round = reflect_round
                        break
                    handoff_info = execute_result["handoff"]
                    if handoff_info is not None:
                        # F14.9：接管命中短路整个 reflect 循环，不再支付评审成本
                        break
                    final_answer = execute_result["content"]
                    if execute_result["budget_hit"]:
                        # 执行阶段已触顶：不再支付 reflect 的调用成本，直接收尾
                        execute_budget_hit = True
                        break

                    judgment = await self._reflect(
                        ctx=ctx,
                        emit=_emit,
                        llm=llm,
                        reflector_prompt=reflector_prompt,
                        user_input=user_input,
                        plan_tasks=plan_tasks,
                        execute_output=final_answer,
                        usage_total=usage_total,
                        reflect_round=reflect_round,
                        model_id=model_id,
                    )
                    reflect_history.append(judgment)

                    if judgment.get("done"):
                        break
                    if token_budget and usage_total["total_tokens"] >= token_budget:
                        # 0074 PRD F11.1：深度模式下 plan/reflect 的消耗也计入预算
                        execute_budget_hit = True
                        break

                    suggestion = str(judgment.get("suggestion") or judgment.get("critique") or "")
                    if not suggestion:
                        break
                    execution_messages.append(
                        {
                            "role": "user",
                            "content": f"上一轮结果未达标：{suggestion}。请基于上述反馈继续推进，避免重复已完成的步骤。",
                        }
                    )

            # M4-d PRD F19.2：收敛终稿后接质量门（在节点层，不侵入 react 内核）。
            # 跳过口径：审批挂起轮/接管轮/预算触顶轮/空答案轮/子 run（C8：
            # workflow_chain 非空即委派或工作流子调用，防成本逐层放大）。
            # 门置于审批 return 之前，使重生途中新产生的挂起/接管仍能走原通道出快照。
            gate_outcome: dict[str, Any] | None = None
            if (
                quality_gate["enabled"]
                and not workflow_chain
                and awaiting_info is None
                and handoff_info is None
                and not execute_budget_hit
                and final_answer.strip()
            ):
                gate_state = _GateState(
                    answer=final_answer,
                    messages=execution_messages,
                    observations=last_observations,
                    reflect_round=last_round,
                )
                gate_outcome = await self._apply_quality_gate(
                    _GateContext(
                        gate=quality_gate,
                        state=gate_state,
                        llm=llm,
                        model_id=model_id,
                        question=user_input,
                        usage_total=usage_total,
                        token_budget=token_budget,
                        emit=_emit,
                        do_execute=_do_execute,
                    )
                )
                final_answer = gate_state.answer
                awaiting_info = gate_state.awaiting
                handoff_info = gate_state.handoff
                execute_budget_hit = gate_state.budget_hit
                # 批末 review P1-1：重生途中新产生的挂起，审批续跑轮次以门内推进后的
                # 真实轮为准——恒用门外旧值会让批准后的续跑复跑已完成轮次、放大成本
                awaiting_round = gate_state.reflect_round

            if awaiting_info is not None:
                # 0074 PRD F10：本轮含未获批的敏感工具调用，整轮挂起，
                # 执行现场经 outputs.snapshot 透出给消费方（ChatService）持久化
                return NodeResult(
                    outputs={
                        "output": "",
                        "plan": plan_tasks,
                        "model": model_id,
                        "awaiting_approval": True,
                        "approval": {
                            "type": "tool_approval",
                            "node_id": ctx.node_id,
                            "iteration": awaiting_info["iteration"],
                            "reflect_round": awaiting_round,
                            "pending_tool_calls": awaiting_info["pending_tool_calls"],
                            "awaiting_calls": awaiting_info["awaiting_calls"],
                        },
                        "snapshot": {
                            "messages": execution_messages,
                            "plan_tasks": plan_tasks,
                            "reflect_round": awaiting_round,
                            "reflect_history": reflect_history,
                            "usage": usage_total,
                        },
                    },
                    usage=usage_total,
                )

            if execute_budget_hit:
                final_finish_reason = BUDGET_EXCEEDED_REASON
            elif handoff_info is not None:
                # M4 PRD F14.9：接管收尾的 finish_reason 复用预算的 outputs 覆盖通道
                final_finish_reason = (
                    HANDED_BACK_REASON if handoff_info["returned"] else HANDED_OFF_REASON
                )

            outputs: dict[str, Any] = {
                "output": final_answer,
                "plan": plan_tasks,
                "reflect_history": reflect_history,
                "model": model_id,
            }
            if final_finish_reason:
                # 仅预算触顶/接管短路时透出 finish_reason（正常收敛沿用 llm_end 通道的语义，
                # chat 侧 _map_canvas_trace 读到该键会覆盖 result 帧 finish_reason）
                outputs["finish_reason"] = final_finish_reason
            if handoff_info is not None:
                # C1：内核 payload 为纯 dict（str/int/bool/None），天然 JSONB 可序列化；
                # 消费方（ChatService，T-c7）据此切换或归位会话路由态
                outputs["handoff"] = handoff_info
            if gate_outcome is not None:
                # M4-d F19.2：judge 终判 additive 透出（门关/判废时不写该键，门关态帧与基线逐字段一致）
                outputs["judge"] = gate_outcome
            return NodeResult(outputs=outputs, usage=usage_total)
        finally:
            # M4-b F17.2：一切出口（正常收敛 / 审批挂起 return / 异常上抛）
            # 必须关闭 run 级 MCP 连接，close 幂等且吞错；
            # 会话池档（F17.4）下 mcp_sessions 恒空，连接由池按 TTL/LRU 驱逐回收
            for session in mcp_sessions.values():
                await session.close()

    # ---------- PLAN ----------
    async def _plan(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        planner_prompt: str,
        user_input: str,
        usage_total: dict[str, int],
        model_id: str = "",
    ) -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_input},
        ]
        await emit(
            "prompt_text",
            {
                "phase": "plan",
                "messages": _messages_for_trace(messages),
            },
        )
        chat_kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
        if model_id:
            chat_kwargs["model"] = model_id
        try:
            resp = await llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan 阶段 LLM 调用失败: %s", exc)
            return [{"id": "t1", "goal": user_input, "acceptance": "直接回答用户问题"}]

        accumulate_usage(usage_total, resp.usage)
        plan_text = getattr(resp, "content", "") or ""
        await emit(
            "prompt_text",
            {
                "phase": "plan",
                "role": "assistant",
                "content": plan_text,
            },
        )
        parsed = _safe_json(plan_text)
        tasks = parsed.get("tasks") if isinstance(parsed, dict) else None
        if not isinstance(tasks, list) or not tasks:
            return [{"id": "t1", "goal": user_input, "acceptance": "直接回答用户问题"}]
        return [t for t in tasks if isinstance(t, dict)]

    # ---------- EXECUTE（ReAct 循环，走共享内核 react.run_react_loop）----------
    async def _execute(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        tool_specs: list[LLMToolSpec],
        tool_executor: Any,
        messages: list[dict[str, Any]],
        model_id: str,
        max_tool_rounds: int,
        usage_total: dict[str, int],
        reflect_round: int,
        chat_kwargs: dict[str, Any] | None = None,
        knowledge_chunks: dict[str, list[dict[str, Any]]] | None = None,
        token_budget: int | None = None,
        react_approval: dict[str, Any] | None = None,
        react_handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 20260731 双轨合并：内层 ReAct 循环收敛到 react.run_react_loop，
        # 本方法只负责把内核事件映射为画布 trace 事件（既有协议名与字段保持不变）。
        # 20261106 P3 服务端兼容契约：additive 补齐 chat SSE 映射所需字段
        # （iteration/tools/usage/finish_reason/id/tool_call_id/arguments_parsed/is_error），
        # 画布旧消费方读取的原有键语义不变。
        # 异常范围与迁移前一致：只兜 LLM 调用（内核 __anext__）异常；
        # 事件映射错误属于代码缺陷，照常上抛，不得伪装成模型回复。
        final_content = ""
        budget_hit = False
        awaiting: dict[str, Any] | None = None
        handoff: dict[str, Any] | None = None
        # M4-d F19.2：工具观察项收集（质量门 judge 参考资料，单条与总量截断见 GATE_* 常量）
        observations: list[str] = []
        event_iter = run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=tool_specs,
            tool_executor=tool_executor,
            max_rounds=max_tool_rounds,
            chat_kwargs=chat_kwargs or {},
            max_rounds_message="（execute 达到最大工具轮次）",
            token_budget=token_budget,
            usage_base=usage_total,
            **(react_approval or {}),
            **(react_handoff or {}),
        ).__aiter__()
        while True:
            try:
                event = await event_iter.__anext__()
            except StopAsyncIteration:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("execute 阶段 LLM 调用失败: %s", exc)
                final_content = f"{EXECUTE_ERROR_PREFIX} {exc}"
                break

            payload = event.payload
            if event.kind == "llm_start":
                await emit(
                    "prompt_text",
                    {
                        "phase": "execute",
                        "reflect_round": reflect_round,
                        "tool_round": payload["iteration"] - 1,
                        "iteration": payload["iteration"],
                        "tools": payload["tools"],
                        "messages": _messages_for_trace(payload["messages"]),
                    },
                )
            elif event.kind == "llm_end":
                # 逐轮累计 usage：即使后续轮次 LLM 异常，已消耗 token 不丢
                accumulate_usage(usage_total, payload["usage"])
                await emit(
                    "prompt_text",
                    {
                        "phase": "execute",
                        "reflect_round": reflect_round,
                        "tool_round": payload["iteration"] - 1,
                        "iteration": payload["iteration"],
                        "role": "assistant",
                        "content": payload["content"],
                        "usage": payload["usage"],
                        "finish_reason": payload["finish_reason"],
                        "tool_calls": [
                            {"id": tc["id"], "name": tc["name"], "arguments": tc["arguments"]}
                            for tc in payload["tool_calls"]
                        ],
                    },
                )
            elif event.kind == "tool_start":
                await emit(
                    "tool_call_start",
                    {
                        "name": payload["name"],
                        "arguments": payload["arguments_raw"],
                        "tool_call_id": payload["tool_call_id"],
                        "arguments_parsed": payload["arguments"],
                        "reflect_round": reflect_round,
                        "tool_round": payload["tool_round"],
                    },
                )
            elif event.kind == "tool_end":
                chunks_meta = (
                    knowledge_chunks.pop(payload["name"], None) if knowledge_chunks else None
                )
                observations.append(str(payload["observation"] or "")[:GATE_OBSERVATION_TRIM])
                await emit(
                    "tool_call_end",
                    {
                        "name": payload["name"],
                        "arguments": payload["arguments_raw"],
                        "tool_call_id": payload["tool_call_id"],
                        "is_error": payload["is_error"],
                        "reflect_round": reflect_round,
                        "tool_round": payload["tool_round"],
                        "observation": payload["observation"],
                        # 0074 PRD F5.3：知识库命中来源（additive，非检索工具无此键）
                        **({"chunks_meta": chunks_meta} if chunks_meta else {}),
                    },
                )
            elif event.kind == "approval_required":
                # 0074 PRD F10：整轮挂起。透出 trace 供运行详情页展示，
                # payload 交回 run() 组装 approval/snapshot 输出
                awaiting = payload
                await emit(
                    "tool_approval_required",
                    {
                        "phase": "execute",
                        "reflect_round": reflect_round,
                        **payload,
                    },
                )
            elif event.kind == "handoff":
                # M4 PRD F14.9：接管/归位整轮短路。trace 供运行详情页展示，
                # payload 交回 run() 组装 handoff/finish_reason 输出
                handoff = payload
                await emit(
                    "tool_handoff",
                    {
                        "phase": "execute",
                        "reflect_round": reflect_round,
                        **payload,
                    },
                )
            elif event.kind == "result":
                final_content = payload["content"]
                budget_hit = payload["finish_reason"] == BUDGET_EXCEEDED_REASON

        return {
            "content": final_content,
            "budget_hit": budget_hit,
            "awaiting": awaiting,
            "handoff": handoff,
            # M4-d F19.2：additive 观察项（仅质量门消费；门关通道不读取）
            "observations": observations[-GATE_MAX_OBSERVATIONS:],
        }

    # ---------- 质量门（M4 PRD F19.2）----------
    async def _apply_quality_gate(self, gc: _GateContext) -> dict[str, Any] | None:
        """对收敛终稿跑 judge 打分与有限次重生，返回 outputs.judge 终判。

        返回 None 表示重生途中出现审批挂起/接管短路，门结论作废（gc.state 已同步
        更新，调用方按原通道出快照/切路由）；达 maxRegen 仍不过、judge 调用异常、
        预算耗尽均 fail-open 放行（U13 裁决 + 验收 7），judge 异常时带 error 标记。
        阈值判定在本消费方（score >= passScore），不信内核 payload.passed——
        内核缺省 7 兜底会与自定义 passScore 漂移。
        """
        gate = gc.gate
        max_regen = int(gate["maxRegen"])
        judge_model_id = gate["judgeModel"] or gc.model_id
        judge_llm = _bind_judge_llm(gc.llm, judge_model_id)
        refs: list[str] | None = gc.state.observations or None
        attempts = 0
        while True:
            attempts += 1
            try:
                verdict = await judge(
                    judge_llm,
                    model=judge_model_id,
                    rubric=gate["rubric"],
                    question=gc.question,
                    answer=gc.state.answer,
                    context_refs=refs,
                )
            except Exception as exc:  # noqa: BLE001
                # 批末 review：带堆栈，judge 传输层异常与解析异常需可区分排查
                logger.warning("质量门 judge 调用失败，fail-open 放行原答案: %s", exc, exc_info=True)
                await gc.emit(
                    "judge",
                    {
                        "score": None,
                        "passed": False,
                        "attempts": attempts,
                        "model": judge_model_id,
                        "error": True,
                    },
                )
                return {"score": None, "passed": False, "attempts": attempts, "error": True}
            accumulate_usage(gc.usage_total, verdict.usage)
            passed = verdict.score >= gate["passScore"]
            await gc.emit(
                "judge",
                {"score": verdict.score, "passed": passed, "attempts": attempts, "model": judge_model_id},
            )
            outcome: dict[str, Any] = {"score": verdict.score, "passed": passed, "attempts": attempts}
            if passed or attempts > max_regen:
                return outcome
            if gc.token_budget and gc.usage_total["total_tokens"] >= gc.token_budget:
                # F19.2：judge 自身消耗已计入预算，触顶即不再付重生成本，终判留档
                return outcome
            gc.state.messages.append(
                {
                    "role": "user",
                    "content": (
                        f"质量门评审：回答未达标（{verdict.score}/{gate['passScore']}），"
                        f"评审意见：{verdict.critique}。请针对性修正后直接给出最终回答，不要重复已完成的步骤。"
                    ),
                }
            )
            # 批末 review P1-1：重生推进一个真实轮次，挂起/接管走原通道时
            # 快照轮次与现场自洽（续跑从该轮起点继续，不复跑已完成轮）
            gc.state.reflect_round += 1
            execute_result = await gc.do_execute(gc.state.reflect_round)
            gc.state.awaiting = execute_result["awaiting"]
            gc.state.handoff = execute_result["handoff"]
            if gc.state.awaiting is not None or gc.state.handoff is not None:
                # 重生途中进入审批/接管通道：门结论作废，挂起现场与接管语义优先透出
                return None
            gc.state.budget_hit = execute_result["budget_hit"]
            new_answer = str(execute_result["content"] or "")
            if not new_answer.strip() or new_answer.startswith(EXECUTE_ERROR_PREFIX):
                # 批末 review P1-2：重生 execute 异常时内核回异常桩，视同重生失败，
                # 保留原答案与最后一次有效判定 fail-open 放行
                return outcome
            gc.state.answer = new_answer
            gc.state.observations = list(execute_result.get("observations") or [])
            refs = gc.state.observations or None
            if gc.state.budget_hit:
                # 重生途中触顶：保留最后一次判定留档，收尾走预算通道
                return outcome

    # ---------- REFLECT ----------
    async def _reflect(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        reflector_prompt: str,
        user_input: str,
        plan_tasks: list[dict[str, Any]],
        execute_output: str,
        usage_total: dict[str, int],
        reflect_round: int,
        model_id: str = "",
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": reflector_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": user_input,
                        "plan": plan_tasks,
                        "execution_result": execute_output,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        await emit(
            "prompt_text",
            {
                "phase": "reflect",
                "reflect_round": reflect_round,
                "messages": _messages_for_trace(messages),
            },
        )
        chat_kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
        if model_id:
            chat_kwargs["model"] = model_id
        try:
            resp = await llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reflect 阶段 LLM 调用失败: %s", exc)
            return {"done": True, "critique": f"reflect LLM 失败：{exc}"}
        accumulate_usage(usage_total, resp.usage)
        reflect_text = getattr(resp, "content", "") or ""
        await emit(
            "prompt_text",
            {
                "phase": "reflect",
                "reflect_round": reflect_round,
                "role": "assistant",
                "content": reflect_text,
            },
        )
        parsed = _safe_json(reflect_text)
        if not isinstance(parsed, dict):
            return {"done": True, "critique": "reflect 输出无法解析，直接收尾"}
        return parsed

    # ---------- 消息组装 ----------
    @staticmethod
    def _build_execution_messages(
        system_prompt: str,
        user_input: str,
        plan_tasks: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
        summary: str = "",
        memories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        system = system_prompt or "你是一个能干的助手。"
        if plan_tasks:
            system = f"{system}\n\n任务清单：{json.dumps(plan_tasks, ensure_ascii=False)}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # M4 PRD F15.5：摘要作独立 system 段插在角色设定之后、历史原文之前
        # （与进程内通道 ChatService._build_chat_messages 同构）
        summary_block = render_summary_block(summary)
        if summary_block:
            messages.append({"role": "system", "content": summary_block})
        # M4 PRD F16.4：长期记忆段紧随摘要段之后（注入位与进程内通道同构）
        memory_block = render_memory_block(memories or [])
        if memory_block:
            messages.append({"role": "system", "content": memory_block})
        # 20261106 P3：chat 兼容通道的多轮历史，拼接位置与旧 chat 通道一致
        # （system 之后、当前问题之前），且同样只保留 user/assistant 非空内容
        for item in history or []:
            role = str(item.get("role") or "")
            content = item.get("content") or ""
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
        # 0074 PRD F9：携带图片时 user content 组装为 OpenAI multi-modal parts
        # （是否放行由调用方按 visionEnabled 门控后传入）
        user_content: Any = build_multimodal_content(user_input, images) if images else user_input
        messages.append({"role": "user", "content": user_content})
        return messages

    # ---------- 知识库检索（0074 PRD F5）----------
    async def _retrieve_always_reference(
        self,
        ctx: NodeContext,
        dataset_entries: list[dict[str, Any]],
        user_input: str,
    ) -> str:
        """always 模式库执行前各检索一次，拼成 system 参考资料段（免模型自行路由）。

        单库失败只跳过该库并告警：注入参考资料是增强手段，缺参考不应中断对话；
        onDemand 库不在这里检索（由模型经 knowledge_search_N 工具按需触发）。
        """
        always_entries = [e for e in dataset_entries if e["mode"] == "always"]
        if not always_entries or not user_input:
            return ""
        parts: list[str] = []
        for entry in always_entries:
            try:
                observation = await _knowledge_search(ctx, entry, user_input)
            except Exception as exc:  # noqa: BLE001
                logger.warning("always 知识库注入失败 dataset=%s: %s", entry["datasetId"], exc)
                continue
            if observation and observation != KNOWLEDGE_EMPTY_MESSAGE:
                label = entry["name"] or entry["datasetId"]
                parts.append(f"【{label}】\n{observation}")
        if not parts:
            return ""
        return (
            "\n\n参考资料（知识库自动检索，回答请优先依据，检索不到再按常识回答）：\n"
            + "\n\n".join(parts)
        )


# ---------- helpers ----------
def _safe_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # 兼容模型输出 ```json ... ``` 包裹
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None


def _resolve_run_context(raw: Any) -> Any:
    """还原 chat 兼容通道传入的运行上下文（20261106 review 修正）。

    画布入参会进 run 表 JSONB 与 graph state，只能是 json.dumps 可序列化形态，
    因此 chat 侧传 AgentRunContext.to_storage_dict() 平铺字典，这里还原为对象；
    已是 AgentRunContext 实例（进程内直调/测试）时原样透传，非法字典返回 None。
    """
    if isinstance(raw, dict):
        return AgentRunContext.from_storage_dict(raw)
    return raw


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


TRACE_MESSAGE_CONTENT_LIMIT = 4000


def _messages_for_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 messages 精简到前端可展示的形态：tool_calls 去掉冗余 schema，长 content 截断。"""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if len(content) > TRACE_MESSAGE_CONTENT_LIMIT:
            content = (
                content[:TRACE_MESSAGE_CONTENT_LIMIT] + f"... [truncated {len(content)} chars]"
            )
        item: dict[str, Any] = {"role": role, "content": content}
        if m.get("tool_calls"):
            item["tool_calls"] = [
                {
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments"),
                }
                for tc in m["tool_calls"]
            ]
        if m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        out.append(item)
    return out


def _parse_dataset_entries(raw: Any) -> list[dict[str, Any]]:
    """datasets 配置 → 归一化条目列表（跳过缺 datasetId 项；mode 非法落 onDemand）。"""
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("datasetId") or "").strip()
        if not dataset_id:
            continue
        mode = str(item.get("mode") or "onDemand")
        entries.append(
            {
                "datasetId": dataset_id,
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "mode": mode if mode in DATASET_MODES else "onDemand",
                "topK": _to_int(item.get("topK")) or DEFAULT_KNOWLEDGE_TOP_K,
            }
        )
    return entries


def _is_reserved_tool_name(name: str) -> bool:
    """合成工具保留前缀（知识库 workflow 与 MCP 同名会互相覆盖，配置面已禁止用户占用）。

    M4-c F14.3：agent_{slug} 委派工具同属合成名，前缀一并保留。
    """
    return (
        name.startswith(KNOWLEDGE_TOOL_NAME_PREFIX)
        or name.startswith(WORKFLOW_TOOL_NAME_PREFIX)
        or name.startswith(AGENT_TOOL_NAME_PREFIX)
    )


def _mcp_fingerprint(
    server_url: str, headers: dict[str, str] | None
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """F17.2 run 级会话去重键：url + 排序后的 headers（同键共享一次握手）。"""
    return (server_url, tuple(sorted((headers or {}).items())))


def _parse_mcp_session_scope(raw: Any) -> str:
    """mcpSession.scope 运行期解析（F17.4）：缺省/非法一律回落 run 档。"""
    if isinstance(raw, dict) and str(raw.get("scope") or "") in MCP_SESSION_SCOPES:
        return str(raw["scope"])
    return DEFAULT_MCP_SESSION_SCOPE


def _mcp_tenant_label(tenant_id: Any) -> str:
    """治理/观测的租户标签：与 ToolGateway._tenant_label 同口径。"""
    if tenant_id is None or tenant_id == PLATFORM_TENANT_ID:
        return "platform"
    return str(tenant_id)[:8]


def _observe_mcp_call(tenant: str, server: str, tool: str, status: str, started: float) -> None:
    """上报一次 MCP 调用观测；端口实现不得影响主链路。"""
    mcp_observer().observe_call(
        McpCallRecord(
            tenant=tenant,
            server=server,
            tool=tool,
            status=status,
            duration_seconds=time.monotonic() - started,
        )
    )


async def _execute_mcp_tool(
    entry: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    sessions: dict[Any, McpSession],
    *,
    pool: McpSessionPool | None = None,
    conversation_id: str = "",
    tenant: str = "platform",
) -> str:
    """执行 MCP 工具：SSRF 复检 → 治理（熔断/限流）→ 会话调用 → 观测记账。

    配置保存期 discover 已校验过地址，但运行期配置可被改写/快照可被伪造，
    执行路径必须再过一次 validate_outbound_url；拦截以 McpClientError 抛出，
    由 ReAct 内核转 "[error]" observation，不发起任何连接。

    M4-b F17.4/F17.5/F17.6：pool 非空走会话级连接池（scope=conversation），
    否则按指纹取 run 级会话；熔断/限流与 HTTP 工具同参口径（tenant+server 维度）；
    每次调用向 MCP 观测端口上报耗时与状态口径。
    """
    server_url = entry["serverUrl"]
    try:
        validate_outbound_url(server_url)
    except ValidationError as exc:
        raise McpClientError(f"MCP server 地址不安全：{exc.message}") from exc

    started = time.monotonic()
    breaker = get_mcp_breaker()
    limiter = get_mcp_limiter()
    breaker_key = f"{tenant}:mcp:{server_url}"
    if not await breaker.allow(breaker_key):
        logger.info("mcp circuit open server=%s tenant=%s", server_url, tenant)
        _observe_mcp_call(tenant, server_url, tool_name, MCP_STATUS_REJECTED, started)
        raise McpClientError("MCP 服务当前不可用（服务熔断），请告知用户稍后重试或换一种方式。")
    if not await limiter.allow(tenant):
        logger.info("mcp rate limited tenant=%s server=%s", tenant, server_url)
        _observe_mcp_call(tenant, server_url, tool_name, MCP_STATUS_REJECTED, started)
        raise McpClientError("MCP 工具调用过于频繁（已限流），请告知用户稍后重试。")

    try:
        if pool is not None:
            text = await pool.call(
                conversation_id,
                server_url,
                entry["headers"],
                entry["timeoutSeconds"],
                tool_name,
                arguments,
            )
        else:
            text = await sessions[entry["fingerprint"]].call_tool(tool_name, arguments)
    except McpClientError as exc:
        await breaker.record_failure(breaker_key)
        _observe_mcp_call(tenant, server_url, tool_name, MCP_STATUS_TRANSPORT_ERROR, started)
        raise exc
    await breaker.record_success(breaker_key)
    # "[error]" 前缀是工具执行错误（isError），连接与治理均正常，单独口径便于排障
    status = MCP_STATUS_TOOL_ERROR if text.startswith("[error]") else MCP_STATUS_OK
    _observe_mcp_call(tenant, server_url, tool_name, status, started)
    return text


def _parse_mcp_entries(raw: Any) -> list[dict[str, Any]]:
    """mcpServers 配置 → 归一化 server 列表（缺 serverUrl 整项跳过；enabledTools 缺 name 跳过）。"""
    if not isinstance(raw, list):
        return []
    servers: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        server_url = str(item.get("serverUrl") or "").strip()
        if not server_url:
            continue
        headers_raw = item.get("headers")
        headers = (
            {str(k): str(v) for k, v in headers_raw.items()}
            if isinstance(headers_raw, dict) and headers_raw
            else None
        )
        tools: list[dict[str, Any]] = []
        for tool in item.get("enabledTools") or []:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            schema = tool.get("inputSchema")
            tools.append(
                {
                    "name": name,
                    "description": str(tool.get("description") or "").strip(),
                    "inputSchema": schema if isinstance(schema, dict) else {},
                }
            )
        servers.append(
            {
                "serverUrl": server_url,
                "name": str(item.get("name") or "").strip(),
                "headers": headers,
                "timeoutSeconds": _parse_mcp_timeout_seconds(item.get("timeoutSeconds")),
                "enabledTools": tools,
            }
        )
    return servers


def _parse_mcp_timeout_seconds(raw: Any) -> float:
    """条目级调用超时（F17.3②）：合法区间 1~300s，缺省/非法回落默认 30s。

    表单侧（T-b3）会做严格校验，此处是运行期兜底：脏配置不能让节点崩溃。
    """
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("mcp timeoutSeconds 非法，回落默认值: %r", raw)
        return DEFAULT_TIMEOUT_SECONDS
    if not 1.0 <= value <= 300.0:
        logger.warning("mcp timeoutSeconds 超出 1~300 区间，回落默认值: %s", value)
        return DEFAULT_TIMEOUT_SECONDS
    return value


def _parse_workflow_entries(raw: Any) -> list[dict[str, Any]]:
    """workflows 配置 → 归一化挂载列表（缺/非法 applicationId 跳过）。"""
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        application_id = str(item.get("applicationId") or "").strip()
        if not application_id:
            continue
        entries.append(
            {
                "applicationId": application_id,
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
        )
    return entries


def _parse_sub_agent_entries(raw: Any) -> list[dict[str, Any]]:
    """subAgents 配置 → 归一化协作挂载列表（M4-c F14.1）。

    缺/非法 applicationId 跳过；mode 非法回落 delegate；delegate+handoff 合计超
    MAX_SUB_AGENTS 截断（表单侧已严格校验，此处是运行期兜底，脏配置不能让节点崩）。
    """
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        application_id = str(item.get("applicationId") or "").strip()
        if not application_id:
            continue
        mode = str(item.get("mode") or "").strip()
        entries.append(
            {
                "applicationId": application_id,
                "mode": mode if mode in SUB_AGENT_MODES else DEFAULT_SUB_AGENT_MODE,
                "toolName": str(item.get("toolName") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
        )
    if len(entries) > MAX_SUB_AGENTS:
        logger.warning("subAgents 挂载数超过上限 %d，忽略尾部条目", MAX_SUB_AGENTS)
        entries = entries[:MAX_SUB_AGENTS]
    return entries


def _hand_back_tool_description() -> str:
    """F14.9 hand_back 归位声明工具描述（接管目标侧自动注入）。"""
    return (
        "结束本次接管，把对话主导权交还给主助手。当用户的请求已办结、或问题"
        "超出你的专长范围应回到主助手时调用；调用后后续对话由主助手应答。"
    )


def _delegation_prompt_section(
    delegation_lines: list[str],
    handoff_lines: list[str] | None = None,
) -> str:
    """F14.5 委派语义提示词段 + M4-c F14.9 接管语义提示词段。

    两类专家挂载分别成段；均无挂载返回空串，系统提示与改造前逐字节一致
    （仅 delegate 挂载时输出与 T-c7 前逐字节一致）。
    """
    section = ""
    if delegation_lines:
        section += (
            "\n\n## 可委派专家\n"
            "当问题命中某位专家的专长时，优先调用对应工具委派，而不是凭自身记忆回答；"
            "子代理看不到当前会话，委派时必须把背景、目标与期望输出写成一条完整自包含的问题放入 question：\n"
            + "\n".join(delegation_lines)
        )
    if handoff_lines:
        section += (
            "\n\n## 可接管专家\n"
            "当用户诉求明确落在某位专家的专长范围、且需要多轮深入处理时，调用对应工具把会话移交给该专家；"
            "移交成功后本会话后续对话由专家直接应答，本轮不要再生成替答：\n"
            + "\n".join(handoff_lines)
        )
    return section


def _parse_workflow_chain(raw: Any) -> list[str]:
    """workflow_chain 运行入参 → 祖先应用 ID 列表（非法形态按空链处理）。"""
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def _workflow_tool_description(entry: dict[str, Any], described: dict[str, Any]) -> str:
    label = entry["name"] or str(described.get("name") or "") or entry["applicationId"]
    detail = entry["description"] or str(described.get("description") or "")
    suffix = f"。{detail}" if detail else ""
    return f"调用工作流「{label}」完成一段固定流程，入参即该工作流的启动参数{suffix}"


def _knowledge_tool_description(entry: dict[str, Any]) -> str:
    label = entry["name"] or entry["datasetId"]
    detail = f"。内容范围：{entry['description']}" if entry["description"] else ""
    return f"检索知识库「{label}」获取与问题相关的资料{detail}。query 传检索关键词或完整问题。"


def _knowledge_query(arguments: dict[str, Any]) -> str:
    """工具入参取 query；兼容模型误传 input/text 的情况。"""
    for key in ("query", "input", "text"):
        value = str(arguments.get(key) or "").strip()
        if value:
            return value
    return ""


async def _knowledge_search(ctx: NodeContext, entry: dict[str, Any], query: str) -> str:
    """单库检索只要 observation 文本（always 注入路径不需要溯源元信息）。"""
    observation, _chunks_meta = await _knowledge_search_detail(ctx, entry, query)
    return observation


KNOWLEDGE_CHUNK_EXCERPT_LIMIT = 160


async def _knowledge_search_detail(
    ctx: NodeContext,
    entry: dict[str, Any],
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    """单库向量检索，返回 (observation 文本, 引用 chunk 元信息)（与 DATASET 节点同口径）。

    依赖 services 里的 embedding + vector_store；缺失或空 query 时抛 RuntimeError，
    onDemand 路径由 ReAct 内核转成 [error] observation 反馈给模型自我纠正。
    chunks_meta 供前端展示来源（0074 PRD F5.3），excerpt 截断防 trace 膨胀。
    """
    if not query:
        raise RuntimeError("检索工具缺少 query 参数")
    if not ctx.services.has("vector_store") or not ctx.services.has("embedding"):
        raise RuntimeError("知识库检索服务未配置（缺少 embedding/vector_store）")
    embedding_service = ctx.services.get("embedding")
    vector_store = ctx.services.get("vector_store")
    vectors = await embedding_service.embed([query])
    if not vectors:
        raise RuntimeError("embedding 服务返回空向量")
    results = await vector_store.search(
        dataset_id=entry["datasetId"],
        query_vector=list(vectors[0]),
        top_k=entry["topK"],
        tenant_id=str(ctx.env.tenant_id),
    )
    if not results:
        return KNOWLEDGE_EMPTY_MESSAGE, []
    lines = [
        f"[{i}]（相关性 {r.score:.3f}）{r.chunk.content}" for i, r in enumerate(results, start=1)
    ]
    text = "\n".join(lines)
    if len(text) > KNOWLEDGE_OBSERVATION_LIMIT:
        text = text[:KNOWLEDGE_OBSERVATION_LIMIT] + "...[已截断]"
    chunks_meta = [
        {
            "dataset_id": r.chunk.dataset_id,
            "dataset_name": entry["name"] or entry["datasetId"],
            "chunk_id": r.chunk.chunk_id,
            "document_id": r.chunk.document_id,
            "score": round(float(r.score), 4),
            "excerpt": (r.chunk.content or "")[:KNOWLEDGE_CHUNK_EXCERPT_LIMIT],
        }
        for r in results
    ]
    return text, chunks_meta


register_node_handler(AgentLoopNodeHandler())
