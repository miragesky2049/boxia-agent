"""共享 ReAct tool-calling 循环内核。

20260731 双轨合并：画布 agent_loop 节点（plan/execute/reflect 的 execute 阶段）与
用户端 chat SSE（ChatService.run_agent_stream）历史上各有一份 ReAct 循环，
行为漂移（工具 schema、参数解析、轮次耗尽文案、异常处理各不相同）。
本模块是唯一实现，两侧都作为其事件消费者：

- 事件流：llm_start -> llm_end -> (tool_start -> tool_end)* -> ... -> result；
  F10 人审新增 approval_required（敏感工具轮整轮挂起前发出，随后 result 以
  finish_reason=awaiting_approval 收尾）；
  F14.9 接管新增 handoff（接管声明轮整轮短路前发出，随后 result 以
  finish_reason=handed_off/handed_back 收尾并携带 handoff 载荷）
- llm 为 duck-typed：async chat(messages, tools, **chat_kwargs) -> LLMResponse；
  chat_kwargs 用于透传 AgentRunContext 等可选参数。
- tool_executor 接受 async 或 sync 可调用：(name, arguments) -> str。

设计约束：内核不 import graph/web 层，事件 payload 只依赖 LLM 响应结构，
消费方各自映射到自己的对外协议（SSE 帧 / trace 事件）。
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from internal.domain.llm.client import LLMToolSpec

logger = logging.getLogger(__name__)

# 工具执行器：按名称 + 参数 dict 执行，返回文本 observation。
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str] | str]

# 轮次耗尽时的兜底回复（chat 侧沿用原用户友好文案；节点侧可覆盖）。
DEFAULT_MAX_ROUNDS_MESSAGE = "已达到最大工具调用轮数，请简化问题后重试。"

# 白名单拒绝文案：模型幻觉/注入调用未声明工具时，不执行、不泄露租户全量目录。
UNDECLARED_TOOL_MESSAGE = "工具未在应用中声明，拒绝执行: {name}"

# 0074 PRD F11.1 单 run token 预算：超界停止循环时的 finish_reason 与兜底文案
BUDGET_EXCEEDED_REASON = "budget_exceeded"
BUDGET_EXCEEDED_MESSAGE = (
    "（本次运行的 token 预算已用尽，停止继续推进，请简化问题或提高预算后重试）"
)

# 0074 PRD F10 人审（M3）：本轮含 sensitiveTools 声明的敏感工具时，不执行该轮
# 任何工具，assistant(tool_calls) 已入 messages 后停止循环等待人工批准。
# 采用"应用层快照暂停"而非 langgraph 节点内 interrupt()：节点级中断恢复会
# 从头重放整个 agent_loop 节点（此前轮次的非幂等工具被重复执行、LLM 重采样
# 可能不再请求同一调用），快照续跑无重放。
AWAITING_APPROVAL_REASON = "awaiting_approval"
APPROVAL_REJECTED_OBSERVATION = (
    "[approval rejected] 用户拒绝了该工具调用{comment}，请不要重试此调用，直接基于现有信息回答。"
)

# M4 PRD F14.9（T-c6）接管门控：本轮 tool_calls 命中 handoff 声明工具（或目标侧
# hand_back 伪工具）时，整轮不执行任何工具，发 handoff 事件后收尾；消费方据此
# 切换/交还会话路由态。与 F10 审批门同机制，但接管门在前（接管优先于挂起）。
HANDED_OFF_REASON = "handed_off"
HANDED_BACK_REASON = "handed_back"


@dataclass(frozen=True)
class ReactEvent:
    """内核产出的一个循环事件。

    kind: "llm_start" / "llm_end" / "tool_start" / "tool_end" / "result" /
    "approval_required" / "handoff"；payload 字段见各事件类型注释，
    消费方按需取子集映射到对外协议。
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ToolCall:
    """内核统一轮内工具调用描述（来源：实时 LLM 响应或快照里待答的 assistant 调用）。"""

    id: str
    name: str
    arguments_raw: str


def _assistant_pending_calls(messages: list[dict[str, Any]]) -> list[_ToolCall]:
    """F10 快照续跑：找末条 assistant(tool_calls) 中尚无 tool 响应的调用。

    仅当最后一条消息是带 tool_calls 的 assistant 且没有任何后续消息时返回；
    其余（正常首轮/已结束轮）返回空列表。
    """
    if not messages:
        return []
    last = messages[-1]
    if str(last.get("role") or "") != "assistant":
        return []
    calls = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("function", {}).get("name") or ""),
            "arguments_raw": str(item.get("function", {}).get("arguments") or ""),
        }
        for item in last.get("tool_calls") or []
        if isinstance(item, dict)
    ]
    return [_ToolCall(**c) for c in calls if c["id"] and c["name"]]


def build_tool_specs(tools_raw: Any) -> list[LLMToolSpec]:
    """把画布 config 的 tools 列表归一化为 LLMToolSpec。

    兼容三种形态：已是 LLMToolSpec、扁平 {name, description, parameters}、
    OpenAI 嵌套 {function: {name, ...}}。缺 name 或非法项跳过。
    """
    if not tools_raw or not isinstance(tools_raw, list):
        return []
    specs: list[LLMToolSpec] = []
    for item in tools_raw:
        if isinstance(item, LLMToolSpec):
            specs.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("function", {}).get("name")
        if not name:
            continue
        description = item.get("description") or item.get("function", {}).get("description", "")
        parameters = (
            item.get("parameters")
            or item.get("function", {}).get("parameters")
            or {
                "type": "object",
                "properties": {},
            }
        )
        specs.append(
            LLMToolSpec(name=str(name), description=str(description), parameters=parameters)
        )
    return specs


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """解析模型给出的工具参数。

    统一策略（原两轨分别为 "{}" 与 {"input": raw}）：
    dict 直接用；JSON 可解析且为 dict 用解析结果；其余包装为 {"input": ...}
    让工具按单入参接收，并把原始文本作为 observation 反馈给模型自纠。
    """
    if isinstance(raw, dict):
        return raw
    text = str(raw or "")
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"input": text}
    if isinstance(parsed, dict):
        return parsed
    return {"input": text}


def empty_usage() -> dict[str, int]:
    """usage 聚合字典的零值形态；SSE result 帧/落库 metadata 的键名唯一拼写处。"""
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def accumulate_usage(aggregated: dict[str, int], usage: Any) -> None:
    """把一次响应的 usage（对象或 Mapping，缺键按 0）累加进聚合字典。"""
    if usage is None:
        return
    if isinstance(usage, Mapping):
        getter = lambda key: usage.get(key)  # noqa: E731
    else:
        getter = lambda key: getattr(usage, key, None)  # noqa: E731
    aggregated["prompt_tokens"] += int(getter("prompt_tokens") or 0)
    aggregated["completion_tokens"] += int(getter("completion_tokens") or 0)
    aggregated["total_tokens"] += int(getter("total_tokens") or 0)


def _supports_keyword(func: Any, name: str) -> bool:
    """检查可调用对象是否接受关键字参数 name（显式参数或 **kwargs）。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD or param.name == name:
            return True
    return False


def _filter_chat_kwargs(llm: Any, chat_kwargs: dict[str, Any]) -> dict[str, Any]:
    """按 llm.chat 实际签名过滤扩展 kwargs。

    20260731 review 修正：不用 "TypeError 后去掉 kwargs 重试" 兼容旧桩签名——
    真实 client 若在 HTTP 请求成功后的处理阶段抛 TypeError，重试即重复计费；
    改为调用前签名检查，绝不二次调用。
    """
    if not chat_kwargs:
        return {}
    chat_fn = getattr(llm, "chat", None)
    if chat_fn is None or not callable(chat_fn):
        return dict(chat_kwargs)
    return {k: v for k, v in chat_kwargs.items() if _supports_keyword(chat_fn, k)}


async def _call_llm(
    llm: Any,
    messages: list[dict[str, Any]],
    tool_specs: list[LLMToolSpec],
    extra_kwargs: dict[str, Any],
) -> Any:
    # 仅在声明了工具时传 tools 关键字：与迁移前两侧消费方一致，
    # 兼容签名不含 tools 参数的旧 mock/轻量 LLM
    kwargs: dict[str, Any] = {"messages": messages}
    if tool_specs:
        kwargs["tools"] = tool_specs
    return await llm.chat(**kwargs, **extra_kwargs)


async def _invoke_tool(
    tool_executor: ToolExecutor | None,
    name: str,
    args: dict[str, Any],
) -> tuple[str, bool]:
    """执行工具，返回 (observation, is_error)；异常一律转文本，不中断循环。"""
    if tool_executor is None:
        return f"[error] 工具未注册: {name}", True
    try:
        result = tool_executor(name, args)
        if inspect.isawaitable(result):
            result = await result
        return str(result), False
    except Exception as exc:  # noqa: BLE001 - 工具异常回灌给模型自纠，不上抛
        logger.exception("ReAct 工具执行失败: tool=%s", name)
        return f"[error] {name}: {exc}", True


async def run_react_loop(
    *,
    llm: Any,
    messages: list[dict[str, Any]],
    tool_specs: list[LLMToolSpec],
    tool_executor: ToolExecutor | None,
    max_rounds: int,
    chat_kwargs: dict[str, Any] | None = None,
    max_rounds_message: str = DEFAULT_MAX_ROUNDS_MESSAGE,
    token_budget: int | None = None,
    usage_base: Mapping[str, int] | None = None,
    sensitive_tool_names: Any = None,
    approved_call_ids: Any = None,
    rejected_call_ids: Any = None,
    rejection_comment: str = "",
    handoff_targets: Mapping[str, str] | None = None,
    hand_back_name: str | None = None,
) -> AsyncIterator[ReactEvent]:
    """跑 ReAct tool-calling 循环并以事件流产出过程与结果。

    - messages 就地追加 assistant(tool_calls)+tool 驱动记录，调用方可跨阶段复用
      同一列表；收敛轮的最终 assistant 回复不回填（由调用方落库/输出）；
    - result 事件必发（含正常收敛与轮次耗尽），payload 字段：
      content / reasoning_content / tool_traces / iterations / usage / finish_reason；
    - 执行白名单 = tool_specs 声明的工具名：模型调用未声明工具（幻觉/注入）
      直接拒绝，不触达执行器，防止越过应用配置使用租户级工具目录；
    - 0074 PRD F11.1：token_budget 为正整数时，逐轮累计 usage（含调用方经
      usage_base 传入的本 run 前序阶段消耗）达到预算即停止循环，本轮待执行的
      工具不再调用，result.finish_reason="budget_exceeded"；
    - 0074 PRD F10 人审：sensitive_tool_names 命中且调用 ID 不在
      approved/rejected 集合内时，该轮任何工具都不执行，assistant(tool_calls)
      入 messages 后发 approval_required 事件并收尾
      result.finish_reason="awaiting_approval"；调用方据此保存快照。批准/拒绝
      后重进本循环续跑：末条 assistant 仍带未回答 tool_calls 时先排空该轮
      （approved 集合正常执行、rejected 集合回灌拒绝 observation，均不再门控），
      再继续 LLM 轮次。max_rounds 预算按续跑轮重新起算（成本上限由 token_budget
      经 usage_base 跨续跑累计兜底）；
    - M4 PRD F14.9 接管门控：handoff_targets 为"接管声明工具名 → 目标应用 ID"
      映射，hand_back_name 为目标侧归位声明工具名；本轮调用命中其一（含快照续跑
      轮）时该轮任何工具都不执行，发 handoff 事件后收尾
      result.finish_reason="handed_off"/"handed_back"，且 result 载荷附加
      handoff 键（仅此路径出现，未命中载荷与改造前逐字段一致）。接管门排在
      人审门之前：同轮并存时接管生效，不产生审批挂起；
    - LLM 调用异常原样上抛，由消费方决定兜底文案。
    """
    extra = _filter_chat_kwargs(llm, chat_kwargs or {})
    allowed_names = {spec.name for spec in tool_specs}
    sensitive_names = {str(name) for name in (sensitive_tool_names or set())}
    approved_ids = {str(cid) for cid in (approved_call_ids or set())}
    rejected_ids = {str(cid) for cid in (rejected_call_ids or set())}
    handoff_map = {str(name): str(app_id) for name, app_id in (handoff_targets or {}).items()}
    hand_back = str(hand_back_name or "")
    usage_total = empty_usage()
    accumulate_usage(usage_total, usage_base)
    tool_traces: list[dict[str, Any]] = []
    final_content = ""
    final_reasoning = ""
    finish_reason = "stop"
    iterations = 0
    handoff_payload: dict[str, Any] | None = None

    def _unapproved_sensitive(calls: list[_ToolCall]) -> list[_ToolCall]:
        return [
            c
            for c in calls
            if c.name in sensitive_names and c.id not in approved_ids and c.id not in rejected_ids
        ]

    def _handoff_hit(calls: list[_ToolCall]) -> tuple[_ToolCall, bool] | None:
        """F14.9：本轮调用中首个接管命中（调用, 是否归位）；未命中返回 None。"""
        if not handoff_map and not hand_back:
            return None
        for c in calls:
            if hand_back and c.name == hand_back:
                return c, True
            if c.name in handoff_map:
                return c, False
        return None

    async def _drain_round(calls: list[_ToolCall], round_idx: int) -> AsyncIterator[ReactEvent]:
        """执行一轮工具调用：逐调用发 tool_start/tool_end 并回灌 messages/traces。"""
        for tc in calls:
            args = parse_tool_arguments(tc.arguments_raw)
            yield ReactEvent(
                "tool_start",
                {
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "arguments": args,
                    "arguments_raw": tc.arguments_raw,
                    "tool_round": round_idx,
                },
            )
            if tc.id in rejected_ids:
                # F10 人审拒绝：不触达执行器，固定文案回灌让模型基于现有信息收尾
                observation = APPROVAL_REJECTED_OBSERVATION.format(
                    comment=f"（理由：{rejection_comment}）" if rejection_comment else ""
                )
                is_error = True
            elif tc.name not in allowed_names:
                # 白名单拒绝：不回显租户工具目录，仅提示未声明（token 也省给模型自纠）
                observation = UNDECLARED_TOOL_MESSAGE.format(name=tc.name)
                is_error = True
            else:
                observation, is_error = await _invoke_tool(tool_executor, tc.name, args)
            yield ReactEvent(
                "tool_end",
                {
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "arguments": args,
                    "arguments_raw": tc.arguments_raw,
                    "tool_round": round_idx,
                    "observation": observation,
                    "is_error": is_error,
                },
            )
            tool_traces.append(
                {
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "observation": observation,
                    "is_error": is_error,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": observation,
                }
            )

    # F10 快照续跑：末条 assistant 带未回答 tool_calls 时，第 0 轮不请求 LLM，
    # 直接排空快照里的那一轮。
    resume_pending = _assistant_pending_calls(messages)

    for round_idx in range(max_rounds):
        iterations = round_idx + 1
        if round_idx == 0 and resume_pending:
            calls = resume_pending
        else:
            yield ReactEvent(
                "llm_start",
                {
                    "iteration": iterations,
                    "messages": list(messages),
                    "tools": [spec.to_openai() for spec in tool_specs],
                },
            )

            resp = await _call_llm(llm, messages, tool_specs, extra)
            content = getattr(resp, "content", "") or ""
            reasoning = getattr(resp, "reasoning_content", "") or ""
            resp_tool_calls = list(getattr(resp, "tool_calls", None) or [])
            round_usage = empty_usage()
            accumulate_usage(round_usage, getattr(resp, "usage", None))
            accumulate_usage(usage_total, round_usage)
            finish_reason = getattr(resp, "finish_reason", None) or finish_reason

            yield ReactEvent(
                "llm_end",
                {
                    "iteration": iterations,
                    "content": content,
                    # 深度思考模型的分析段（非 llm.py 消费方不使用，additive 字段）
                    "reasoning_content": reasoning,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                        for tc in resp_tool_calls
                    ],
                    # 本轮 usage（与 llm_end 的 SSE 契约一致；累计值在 result 事件里）
                    "usage": round_usage,
                    "finish_reason": finish_reason,
                },
            )

            if not resp_tool_calls:
                final_content = content
                final_reasoning = reasoning
                # 收敛轮不回填 assistant 消息：与迁移前 agent_loop/llm 节点一致，
                # messages 只承载"驱动下一轮所需"的 assistant(tool_calls)+tool 记录
                break

            if token_budget and usage_total["total_tokens"] >= token_budget:
                # 0074 PRD F11.1：还要继续调工具才判预算，已收敛的回答在上面正常返回；
                # 超界轮的工具不执行（成本不再增长），以固定文案收尾并标注 finish_reason
                finish_reason = BUDGET_EXCEEDED_REASON
                final_content = BUDGET_EXCEEDED_MESSAGE
                final_reasoning = reasoning
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in resp_tool_calls
                    ],
                }
            )
            calls = [
                _ToolCall(id=tc.id, name=tc.function.name, arguments_raw=tc.function.arguments)
                for tc in resp_tool_calls
            ]

        hit = _handoff_hit(calls)
        if hit is not None:
            # F14.9：接管整轮短路（同轮其余调用也不执行），与 F10 整轮挂起同机制；
            # 接管轮的 assistant(tool_calls) 已按既有路径入 messages，正文不作最终回答
            call, returned = hit
            handoff_payload = {
                "iteration": iterations,
                "tool_round": round_idx,
                "tool_name": call.name,
                "tool_call_id": call.id,
                "arguments_raw": call.arguments_raw,
                "application_id": None if returned else handoff_map.get(call.name),
                "returned": returned,
            }
            yield ReactEvent("handoff", handoff_payload)
            finish_reason = HANDED_BACK_REASON if returned else HANDED_OFF_REASON
            break

        blocked = _unapproved_sensitive(calls)
        if blocked:
            # F10：整轮挂起（含同轮非敏感调用也不先执行），保证快照里
            # "待答调用 = 本轮全部调用"，续跑排空顺序与模型意图一致。
            yield ReactEvent(
                "approval_required",
                {
                    "iteration": iterations,
                    "tool_round": round_idx,
                    "pending_tool_calls": [
                        {"id": c.id, "name": c.name, "arguments_raw": c.arguments_raw}
                        for c in calls
                    ],
                    "awaiting_calls": [
                        {"id": c.id, "name": c.name, "arguments_raw": c.arguments_raw}
                        for c in blocked
                    ],
                },
            )
            finish_reason = AWAITING_APPROVAL_REASON
            break

        async for drain_event in _drain_round(calls, round_idx):
            yield drain_event
    else:
        final_content = max_rounds_message

    result_payload: dict[str, Any] = {
        "content": final_content,
        "reasoning_content": final_reasoning,
        "tool_traces": tool_traces,
        "iterations": iterations,
        "usage": usage_total,
        "finish_reason": finish_reason,
    }
    if handoff_payload is not None:
        # additive：仅接管轮出现该键，消费方（agent_loop 节点）据此透出路由切换
        result_payload["handoff"] = handoff_payload
    yield ReactEvent("result", result_payload)
