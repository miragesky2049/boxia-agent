"""共享 ReAct tool-calling 循环内核。

20260731 双轨合并：画布 agent_loop 节点（plan/execute/reflect 的 execute 阶段）与
用户端 chat SSE（ChatService.run_agent_stream）历史上各有一份 ReAct 循环，
行为漂移（工具 schema、参数解析、轮次耗尽文案、异常处理各不相同）。
本模块是唯一实现，两侧都作为其事件消费者：

- 事件流：llm_start -> llm_end -> (tool_start -> tool_end)* -> ... -> result
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


@dataclass(frozen=True)
class ReactEvent:
    """内核产出的一个循环事件。

    kind: "llm_start" / "llm_end" / "tool_start" / "tool_end" / "result"；
    payload 字段见各事件类型注释，消费方按需取子集映射到对外协议。
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


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
        parameters = item.get("parameters") or item.get("function", {}).get("parameters") or {
            "type": "object",
            "properties": {},
        }
        specs.append(LLMToolSpec(name=str(name), description=str(description), parameters=parameters))
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
) -> AsyncIterator[ReactEvent]:
    """跑 ReAct tool-calling 循环并以事件流产出过程与结果。

    - messages 就地追加 assistant(tool_calls)+tool 驱动记录，调用方可跨阶段复用
      同一列表；收敛轮的最终 assistant 回复不回填（由调用方落库/输出）；
    - result 事件必发（含正常收敛与轮次耗尽），payload 字段：
      content / reasoning_content / tool_traces / iterations / usage / finish_reason；
    - 执行白名单 = tool_specs 声明的工具名：模型调用未声明工具（幻觉/注入）
      直接拒绝，不触达执行器，防止越过应用配置使用租户级工具目录；
    - LLM 调用异常原样上抛，由消费方决定兜底文案。
    """
    extra = _filter_chat_kwargs(llm, chat_kwargs or {})
    allowed_names = {spec.name for spec in tool_specs}
    usage_total = empty_usage()
    tool_traces: list[dict[str, Any]] = []
    final_content = ""
    final_reasoning = ""
    finish_reason = "stop"
    iterations = 0

    for round_idx in range(max_rounds):
        iterations = round_idx + 1
        yield ReactEvent("llm_start", {
            "iteration": iterations,
            "messages": list(messages),
            "tools": [spec.to_openai() for spec in tool_specs],
        })

        resp = await _call_llm(llm, messages, tool_specs, extra)
        content = getattr(resp, "content", "") or ""
        reasoning = getattr(resp, "reasoning_content", "") or ""
        resp_tool_calls = list(getattr(resp, "tool_calls", None) or [])
        round_usage = empty_usage()
        accumulate_usage(round_usage, getattr(resp, "usage", None))
        accumulate_usage(usage_total, round_usage)
        finish_reason = getattr(resp, "finish_reason", None) or finish_reason

        yield ReactEvent("llm_end", {
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
        })

        if not resp_tool_calls:
            final_content = content
            final_reasoning = reasoning
            # 收敛轮不回填 assistant 消息：与迁移前 agent_loop/llm 节点一致，
            # messages 只承载"驱动下一轮所需"的 assistant(tool_calls)+tool 记录
            break

        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in resp_tool_calls
            ],
        })

        for tc in resp_tool_calls:
            args = parse_tool_arguments(tc.function.arguments)
            yield ReactEvent("tool_start", {
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "arguments": args,
                "arguments_raw": tc.function.arguments,
                "tool_round": round_idx,
            })
            if tc.function.name not in allowed_names:
                # 白名单拒绝：不回显租户工具目录，仅提示未声明（token 也省给模型自纠）
                observation = UNDECLARED_TOOL_MESSAGE.format(name=tc.function.name)
                is_error = True
            else:
                observation, is_error = await _invoke_tool(tool_executor, tc.function.name, args)
            yield ReactEvent("tool_end", {
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "arguments": args,
                "arguments_raw": tc.function.arguments,
                "tool_round": round_idx,
                "observation": observation,
                "is_error": is_error,
            })
            tool_traces.append({
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "observation": observation,
                "is_error": is_error,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": observation,
            })
    else:
        final_content = max_rounds_message

    yield ReactEvent("result", {
        "content": final_content,
        "reasoning_content": final_reasoning,
        "tool_traces": tool_traces,
        "iterations": iterations,
        "usage": usage_total,
        "finish_reason": finish_reason,
    })
