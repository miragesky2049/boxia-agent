"""Function Calling Agent Runner：对齐 dify FunctionCallAgentRunner 的 while 主循环。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from internal.engine.context import AgentRunContext
from internal.engine.llm import LLMClient, LLMResponse, LLMToolSpec
from internal.engine.messages import (
    AssistantMessage,
    ChatMessage,
    ToolMessage,
    UserMessage,
    system,
    tool_result,
    user,
)
from internal.engine.tools import Tool, ToolExecutionError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCallTrace:
    """一轮 tool_call 的执行轨迹：供审计、前端展示与调试。"""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    observation: str
    is_error: bool = False


@dataclass(frozen=True)
class AgentRunResult:
    """一次 agent 运行的最终结果。"""

    content: str
    messages: list[ChatMessage]
    tool_traces: list[ToolCallTrace]
    iterations: int
    run_id: str = ""
    conversation_id: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


# 事件回调：runner 在关键节点外抛事件，便于上层做 SSE 流式推送。
# event_type ∈ {run_start, llm_start, llm_end, tool_start, tool_end, final}
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


@dataclass
class RunnerOptions:
    """运行期可覆盖参数。"""

    temperature: float | None = None
    max_tokens: int | None = None
    max_iterations: int | None = None


class FunctionCallAgentRunner:
    """基于 OpenAI function calling 的 agent 主循环。

    流程：
      1. 拼装 messages = [system, ...history, user(query)]
      2. while iteration < max_iterations:
         - 调 LLM（带 tools）
         - 若未要求 tool_call -> 结束
         - 逐个执行 tool，结果以 tool 角色消息回灌
      3. 返回最终 assistant 文本与全部 tool 轨迹
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: list[Tool],
        system_prompt: str,
        default_max_iterations: int = 6,
        event_callback: EventCallback | None = None,
    ) -> None:
        self._llm = llm
        self._tools = {tool.name: tool for tool in tools}
        self._system_prompt = system_prompt
        self._default_max_iterations = default_max_iterations
        self._event_callback = event_callback

    async def run(
        self,
        *,
        query: str,
        history: list[ChatMessage] | None = None,
        context: AgentRunContext,
        options: RunnerOptions | None = None,
    ) -> AgentRunResult:
        """执行一轮 agent 调用。"""
        options = options or RunnerOptions()
        max_iterations = options.max_iterations or self._default_max_iterations

        messages: list[ChatMessage] = [system(self._system_prompt)]
        if history:
            messages.extend(history)
        messages.append(user(query))

        tool_specs: list[LLMToolSpec] = [tool.spec() for tool in self._tools.values()]
        tool_traces: list[ToolCallTrace] = []
        total_prompt = 0
        total_completion = 0
        final_content = ""
        finish_reason = "stop"

        await self._emit("run_start", {"run_id": context.run_id, "tools": list(self._tools.keys())})

        for iteration in range(1, max_iterations + 1):
            await self._emit(
                "llm_start",
                {"iteration": iteration, "messages": len(messages), "tools": len(tool_specs)},
            )

            serializable = [self._to_openai_dict(msg) for msg in messages]
            response: LLMResponse = await self._llm.chat(
                messages=serializable,
                tools=tool_specs or None,
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                context=context,
            )
            total_prompt += response.usage.prompt_tokens
            total_completion += response.usage.completion_tokens
            finish_reason = response.finish_reason

            await self._emit(
                "llm_end",
                {
                    "iteration": iteration,
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                        for tc in response.tool_calls
                    ],
                    "usage": response.usage.model_dump(),
                },
            )

            assistant_msg = AssistantMessage(
                content=response.content, tool_calls=response.tool_calls or None
            )
            messages.append(assistant_msg)

            if not response.wants_tool_call:
                final_content = response.content
                break

            for tool_call in response.tool_calls:
                observation, is_error = await self._execute_tool(tool_call, context)
                trace = ToolCallTrace(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.function.name,
                    arguments=self._safe_parse_arguments(tool_call.function.arguments),
                    observation=observation,
                    is_error=is_error,
                )
                tool_traces.append(trace)
                messages.append(tool_result(tool_call.id, observation))
        else:
            # 达到最大迭代次数仍要求 tool_call：以最后一轮 content 兜底返回
            final_content = final_content or (
                "已达到最大工具调用次数，未能完成本次请求，请缩小问题范围后重试。"
            )
            finish_reason = "length"

        await self._emit(
            "final",
            {
                "content": final_content,
                "iterations": len(tool_traces) or 1,
                "tool_traces": [trace.__dict__ for trace in tool_traces],
            },
        )

        return AgentRunResult(
            content=final_content,
            messages=messages,
            tool_traces=tool_traces,
            iterations=len(tool_traces) or 1,
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            usage={"prompt_tokens": total_prompt, "completion_tokens": total_completion},
            finish_reason=finish_reason,
        )

    async def _execute_tool(
        self, tool_call: Any, context: AgentRunContext
    ) -> tuple[str, bool]:
        """执行单个 tool_call；异常归一为文本 observation 回灌给 LLM。"""
        name = tool_call.function.name
        arguments = self._safe_parse_arguments(tool_call.function.arguments)
        await self._emit(
            "tool_start",
            {"tool_call_id": tool_call.id, "name": name, "arguments": arguments},
        )

        tool = self._tools.get(name)
        if tool is None:
            observation = f"错误：未注册的工具 `{name}`，可用工具列表：{list(self._tools.keys())}"
            await self._emit(
                "tool_end",
                {"tool_call_id": tool_call.id, "name": name, "observation": observation, "is_error": True},
            )
            return observation, True

        try:
            observation = await tool.invoke(arguments, context)
            is_error = False
        except ToolExecutionError as exc:
            observation = f"工具执行失败：{exc.message}"
            is_error = True
        except Exception as exc:  # noqa: BLE001 - 兜底：不让单工具异常拖垮主循环
            logger.exception("tool unexpected error tool=%s", name)
            observation = f"工具执行异常：{exc}"
            is_error = True

        await self._emit(
            "tool_end",
            {"tool_call_id": tool_call.id, "name": name, "observation": observation, "is_error": is_error},
        )
        return observation, is_error

    @staticmethod
    def _safe_parse_arguments(raw: str) -> dict[str, Any]:
        """把 LLM 返回的 arguments 字符串解析为 dict；失败时返回空 dict。"""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except (ValueError, TypeError):
            return {"raw": raw}

    @staticmethod
    def _to_openai_dict(message: ChatMessage) -> dict[str, Any]:
        """把内部消息模型序列化为 OpenAI /chat/completions messages 项。"""
        if isinstance(message, ToolMessage):
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }
        if isinstance(message, AssistantMessage):
            payload: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "",
                        },
                    }
                    for tc in message.tool_calls
                ]
            return payload
        # SystemMessage / UserMessage
        return {"role": message.role, "content": message.content}

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """外抛运行事件；回调为 None 时静默跳过。"""
        if self._event_callback is None:
            return
        try:
            result = self._event_callback(event_type, payload)
            if isinstance(result, Awaitable):
                await result
        except Exception:  # noqa: BLE001 - 回调异常不能影响主流程
            logger.warning("event callback failed type=%s", event_type, exc_info=True)


# 避免运行期对 UserMessage 未使用告警（保留类型便于扩展）
__all__ = [
    "AgentRunResult",
    "FunctionCallAgentRunner",
    "RunnerOptions",
    "ToolCallTrace",
    "UserMessage",
]
