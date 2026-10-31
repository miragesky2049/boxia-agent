"""T15：Agent 循环节点 trace 事件单测。

验证 plan/execute/reflect 三阶段通过 ctx.emit_event 外抛：
- prompt_text：每次 LLM 调用前 messages 快照 + 调用后 assistant 内容
- tool_call_start / tool_call_end：execute 阶段每次工具调用前后
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.agent_loop import AgentLoopNodeHandler


class _Usage:
    def __init__(self) -> None:
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.total_tokens = 2


class _ToolCallFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id_: str, name: str, arguments: str) -> None:
        self.id = id_
        self.function = _ToolCallFunction(name, arguments)


class _Resp:
    def __init__(self, content: str, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.usage = _Usage()


class _ScriptedLLM:
    def __init__(self, script: list[_Resp]) -> None:
        self._script = script
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, response_format=None, **kwargs) -> _Resp:
        self.calls.append({"messages": messages})
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return self._script[idx]


def _make_ctx(services: ServiceRegistry, config: dict, user_input: str, emit) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(), user_id=None, run_id=uuid4(),
        thread_id="test", application_id=uuid4(),
    )
    return NodeContext(
        node_id="agent_1",
        node_type=NodeType.AGENT_LOOP.value,
        inputs={"input": user_input},
        config=config,
        env=env,
        services=services,
        emit_event=emit,
    )


def test_agent_loop_emits_prompt_and_tool_trace_events() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(etype: str, payload: dict) -> None:
        events.append((etype, payload))

    tool_executor_calls: list[tuple[str, dict]] = []

    def _tool_executor(name: str, args: dict) -> str:
        tool_executor_calls.append((name, args))
        return "晴，20 度"

    script = [
        _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "查天气"}]})),
        _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')]),
        _Resp(content="北京 20 度。"),
        _Resp(content=json.dumps({"done": True})),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    ctx = _make_ctx(
        services,
        {"modleName": "m", "tools": [{"name": "get_weather", "parameters": {"type": "object", "properties": {}}}]},
        "北京天气",
        _emit,
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert result.outputs["output"] == "北京 20 度。"

    types = [e[0] for e in events]
    # plan 前+后 (2) + execute 两轮各 2 (4) + reflect 前+后 (2) = 8
    assert types.count("prompt_text") == 8
    # 一轮 tool_call_start + tool_call_end
    assert types.count("tool_call_start") == 1
    assert types.count("tool_call_end") == 1

    # 校验 plan 阶段的 prompt_text 带 phase=plan 和 messages
    plan_events = [p for t, p in events if t == "prompt_text" and p.get("phase") == "plan"]
    assert any("messages" in p for p in plan_events)
    assert any(p.get("role") == "assistant" and "tasks" in p.get("content", "") for p in plan_events)

    # tool_call_start 带 name/arguments，tool_call_end 多 observation
    start = next(p for t, p in events if t == "tool_call_start")
    end = next(p for t, p in events if t == "tool_call_end")
    assert start["name"] == "get_weather"
    assert "北京" in start["arguments"]
    assert end["observation"] == "晴，20 度"
