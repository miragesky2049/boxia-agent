"""Agent Runner 主循环单元测试：不依赖数据库，使用 mock LLM。"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.engine.context import AgentRunContext
from internal.engine.llm import LLMClient, LLMResponse
from internal.engine.messages import ToolCall, ToolCallFunction
from internal.engine.runner import FunctionCallAgentRunner, RunnerOptions
from internal.engine.tools import EchoTool


class StubLLM(LLMClient):
    """按预设脚本依次返回响应，用于验证 runner 循环。"""

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: AgentRunContext | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._script:
            return LLMResponse(content="", finish_reason="stop")
        return self._script.pop(0)


def _context() -> AgentRunContext:
    return AgentRunContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        conversation_id="conv-test",
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_runner_returns_final_text_without_tool_call() -> None:
    """LLM 直接返回最终文本时，runner 应立即结束且不调用工具。"""
    llm = StubLLM([LLMResponse(content="你好，我已收到请求。")])
    runner = FunctionCallAgentRunner(
        llm=llm,
        tools=[EchoTool()],
        system_prompt="你是助手",
        default_max_iterations=3,
    )

    result = _run(runner.run(query="hi", context=_context()))

    assert result.content == "你好，我已收到请求。"
    assert result.tool_traces == []
    assert result.finish_reason == "stop"
    assert len(llm.calls) == 1
    sent = llm.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] == "user"
    assert sent[1]["content"] == "hi"


def test_runner_executes_tool_then_finalizes() -> None:
    """第一轮 LLM 请求工具，runner 执行工具并把结果回灌，第二轮返回最终文本。"""
    tool_call = ToolCall(
        id="call-1",
        function=ToolCallFunction(name="echo", arguments='{"text": "hello"}'),
    )
    llm = StubLLM(
        [
            LLMResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls"),
            LLMResponse(content="echo 工具已返回：hello"),
        ]
    )
    runner = FunctionCallAgentRunner(
        llm=llm,
        tools=[EchoTool()],
        system_prompt="你是助手",
        default_max_iterations=3,
    )

    result = _run(runner.run(query="请回显 hello", context=_context()))

    assert result.content == "echo 工具已返回：hello"
    assert len(result.tool_traces) == 1
    trace = result.tool_traces[0]
    assert trace.tool_name == "echo"
    assert trace.arguments == {"text": "hello"}
    assert trace.observation == "echo: hello"
    assert trace.is_error is False

    second_call = llm.calls[1]
    roles = [item["role"] for item in second_call["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    tool_msg = second_call["messages"][-1]
    assert tool_msg["tool_call_id"] == "call-1"
    assert tool_msg["content"] == "echo: hello"


def test_runner_handles_unknown_tool_gracefully() -> None:
    """LLM 请求未注册的工具时，runner 应把错误作为 observation 回灌而不中断。"""
    bad_call = ToolCall(
        id="call-bad",
        function=ToolCallFunction(name="not_exist", arguments="{}"),
    )
    llm = StubLLM(
        [
            LLMResponse(content="", tool_calls=[bad_call], finish_reason="tool_calls"),
            LLMResponse(content="抱歉，该工具不可用。"),
        ]
    )
    runner = FunctionCallAgentRunner(
        llm=llm,
        tools=[EchoTool()],
        system_prompt="你是助手",
    )

    result = _run(runner.run(query="test", context=_context()))

    assert len(result.tool_traces) == 1
    assert result.tool_traces[0].is_error is True
    assert "未注册的工具" in result.tool_traces[0].observation


def test_runner_breaks_at_max_iterations() -> None:
    """LLM 持续要求 tool_call 时，runner 在达到最大迭代后兜底返回。"""
    call = ToolCall(
        id="call-loop",
        function=ToolCallFunction(name="echo", arguments='{"text": "x"}'),
    )
    llm = StubLLM(
        [LLMResponse(content="", tool_calls=[call], finish_reason="tool_calls") for _ in range(5)]
    )
    runner = FunctionCallAgentRunner(
        llm=llm,
        tools=[EchoTool()],
        system_prompt="你是助手",
        default_max_iterations=2,
    )

    result = _run(
        runner.run(
            query="loop",
            context=_context(),
            options=RunnerOptions(max_iterations=2),
        )
    )

    assert result.finish_reason == "length"
    assert "最大工具调用次数" in result.content
