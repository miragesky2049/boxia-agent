"""A4: LLM 节点 ReAct 工具调用循环单测。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.llm import LLMNodeHandler
from internal.engine.llm import LLMToolSpec


class _Usage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _ToolCallFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id_: str, name: str, arguments: str) -> None:
        self.id = id_
        self.function = _ToolCallFunction(name, arguments)


class _Resp:
    def __init__(self, content: str, tool_calls: list[_ToolCall] | None, usage: _Usage) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage
        self.model = "test-model"

    @property
    def wants_tool_call(self) -> bool:
        return bool(self.tool_calls)


class _MockLLM:
    """按脚本顺序返回响应：第一轮带 tool_calls，第二轮纯文本。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tools: list[LLMToolSpec] | None = None,
    ) -> _Resp:
        self.calls.append({"messages": messages, "tools": tools})
        round_idx = len(self.calls)
        if round_idx == 1:
            return _Resp(
                content="",
                tool_calls=[
                    _ToolCall("call_1", "get_weather", '{"city": "北京"}'),
                ],
                usage=_Usage(10, 5),
            )
        return _Resp(
            content="北京今天晴，20 度。",
            tool_calls=None,
            usage=_Usage(20, 15),
        )


def _make_ctx(services: ServiceRegistry, config: dict) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="llm_1",
        node_type=NodeType.LLM.value,
        inputs={"input": "北京天气怎么样"},
        config=config,
        env=env,
        services=services,
    )


def test_llm_node_react_loop_executes_tool_and_returns_final_text() -> None:
    tool_calls_seen: list[tuple[str, dict]] = []

    def _tool_executor(name: str, arguments: dict) -> str:
        tool_calls_seen.append((name, arguments))
        return "晴，20 度"

    mock_llm = _MockLLM()
    services = ServiceRegistry({
        "llm": mock_llm,
        "tool_executor": _tool_executor,
    })

    config = {
        "modleName": "test-model",
        "prompt": "{{input}}",
        "tools": [
            {
                "name": "get_weather",
                "description": "查询天气",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            }
        ],
    }
    ctx = _make_ctx(services, config)

    handler = LLMNodeHandler()
    result = asyncio.run(handler.run(ctx))

    # 最终输出是第二轮纯文本
    assert result.outputs["output"] == "北京今天晴，20 度。"
    # 工具被调用一次
    assert len(tool_calls_seen) == 1
    assert tool_calls_seen[0][0] == "get_weather"
    assert tool_calls_seen[0][1] == {"city": "北京"}
    # 两轮 LLM 调用
    assert len(mock_llm.calls) == 2
    # 第一轮带 tools，第二轮也带 tools（我们把 tools 放在 chat_kwargs 里）
    assert mock_llm.calls[0]["tools"] is not None
    assert mock_llm.calls[1]["tools"] is not None
    # 第二轮 messages 应该包含 assistant tool_calls + tool 结果
    second_messages = mock_llm.calls[1]["messages"]
    assert any(m["role"] == "assistant" and "tool_calls" in m for m in second_messages)
    assert any(m["role"] == "tool" and m["content"] == "晴，20 度" for m in second_messages)
    # usage 累计
    assert result.usage == {
        "prompt_tokens": 30,
        "completion_tokens": 20,
        "total_tokens": 50,
    }


def test_llm_node_tool_executor_unavailable_returns_error_text() -> None:
    """LLM 请求 tool_call 但 services 没注册 tool_executor 时，回灌错误文本。"""

    class _OnceLLM(_MockLLM):
        async def chat(self, **kwargs) -> _Resp:  # type: ignore[override]
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return _Resp(
                    content="",
                    tool_calls=[_ToolCall("call_1", "unknown_tool", "{}")],
                    usage=_Usage(1, 1),
                )
            return _Resp(content="工具不可用，回答结束。", tool_calls=None, usage=_Usage(1, 1))

    mock_llm = _OnceLLM()
    services = ServiceRegistry({"llm": mock_llm})  # 没有 tool_executor

    ctx = _make_ctx(services, {
        "modleName": "test-model",
        "prompt": "{{input}}",
        "tools": [{"name": "unknown_tool", "description": "", "parameters": {}}],
    })

    result = asyncio.run(LLMNodeHandler().run(ctx))
    assert result.outputs["output"] == "工具不可用，回答结束。"
    second_messages = mock_llm.calls[1]["messages"]
    tool_msg = next(m for m in second_messages if m["role"] == "tool")
    assert "工具未注册" in tool_msg["content"]
