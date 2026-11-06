"""20260731 双轨合并：共享 ReAct 内核 react.run_react_loop 单测。

覆盖：事件顺序、多轮工具调用、轮次耗尽、参数解析兜底、executor 异常/缺省、
sync 与 async executor 兼容、chat_kwargs 透传与不支持时的降级重试、usage 聚合。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from internal.domain.agent.react import (
    DEFAULT_MAX_ROUNDS_MESSAGE,
    ReactEvent,
    build_tool_specs,
    parse_tool_arguments,
    run_react_loop,
)
from internal.domain.llm.client import LLMToolSpec


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Function


@dataclass
class _Resp:
    content: str = ""
    tool_calls: list[_ToolCall] = field(default_factory=list)
    usage: _Usage = field(default_factory=_Usage)
    finish_reason: str = "stop"


class _ScriptedLLM:
    """按脚本返回响应；脚本项为异常时抛出。"""

    def __init__(self, script: list[Any]) -> None:
        self._script = script
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *, messages: list, tools: Any = None, **kwargs: Any) -> Any:
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        item = self._script[min(len(self.calls) - 1, len(self._script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


class _StrictLLM:
    """签名不含 **kwargs：额外 chat_kwargs 会触发 TypeError，用于验证降级重试。"""

    def __init__(self, resp: _Resp) -> None:
        self.resp = resp
        self.calls = 0

    async def chat(self, *, messages: list, tools: Any = None) -> _Resp:
        self.calls += 1
        return self.resp


def _collect(gen: Any) -> list[ReactEvent]:
    async def _go() -> list[ReactEvent]:
        return [ev async for ev in gen]

    return asyncio.run(_go())


def _events_by_kind(events: list[ReactEvent]) -> dict[str, list[ReactEvent]]:
    grouped: dict[str, list[ReactEvent]] = {}
    for ev in events:
        grouped.setdefault(ev.kind, []).append(ev)
    return grouped


def _spec(name: str = "get_weather") -> LLMToolSpec:
    return LLMToolSpec(name=name, description="天气", parameters={
        "type": "object", "properties": {"city": {"type": "string"}},
    })


def test_two_rounds_event_order_and_messages_growth() -> None:
    script = [
        _Resp(
            content="",
            tool_calls=[_ToolCall("c1", _Function("get_weather", json.dumps({"city": "北京"})))],
            usage=_Usage(8, 4),
            finish_reason="tool_calls",
        ),
        _Resp(content="北京 20 度。", usage=_Usage(15, 6), finish_reason="stop"),
    ]
    llm = _ScriptedLLM(script)
    seen: list[tuple[str, dict]] = []

    def executor(name: str, args: dict) -> str:
        seen.append((name, args))
        return "晴，20 度"

    messages: list[dict] = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    events = _collect(run_react_loop(
        llm=llm, messages=messages, tool_specs=[_spec()],
        tool_executor=executor, max_rounds=5,
    ))

    assert [ev.kind for ev in events] == [
        "llm_start", "llm_end", "tool_start", "tool_end", "llm_start", "llm_end", "result",
    ]
    result = events[-1].payload
    assert result["content"] == "北京 20 度。"
    assert result["iterations"] == 2
    assert result["usage"] == {"prompt_tokens": 23, "completion_tokens": 10, "total_tokens": 33}
    assert result["tool_traces"][0]["observation"] == "晴，20 度"
    assert result["tool_traces"][0]["is_error"] is False

    # llm_end 的 usage 是本轮而非累计
    first_end = _events_by_kind(events)["llm_end"][0]
    assert first_end.payload["usage"] == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}

    assert seen == [("get_weather", {"city": "北京"})]
    # messages 被就地追加：assistant(tool_calls) + tool；收敛轮不回填 assistant
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool"]
    assert messages[3]["tool_call_id"] == "c1"


def test_max_rounds_exhausted_uses_message_and_counts_iterations() -> None:
    always_tool = _Resp(
        content="",
        tool_calls=[_ToolCall("c", _Function("get_weather", "{}"))],
        usage=_Usage(1, 1),
        finish_reason="tool_calls",
    )
    llm = _ScriptedLLM([always_tool])
    events = _collect(run_react_loop(
        llm=llm, messages=[{"role": "user", "content": "q"}],
        tool_specs=[_spec()], tool_executor=lambda name, args: "ok", max_rounds=3,
    ))
    result = events[-1].payload
    assert result["content"] == DEFAULT_MAX_ROUNDS_MESSAGE
    assert result["iterations"] == 3
    assert len(result["tool_traces"]) == 3

    events2 = _collect(run_react_loop(
        llm=llm, messages=[{"role": "user", "content": "q"}],
        tool_specs=[_spec()], tool_executor=lambda name, args: "ok",
        max_rounds=2, max_rounds_message="（execute 达到最大工具轮次）",
    ))
    assert events2[-1].payload["content"] == "（execute 达到最大工具轮次）"


def test_executor_exception_becomes_error_observation() -> None:
    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", _Function("get_weather", "{}"))]),
        _Resp(content="done"),
    ]

    async def boom(name: str, args: dict) -> str:
        raise RuntimeError("gateway down")

    events = _collect(run_react_loop(
        llm=_ScriptedLLM(script), messages=[{"role": "user", "content": "q"}],
        tool_specs=[_spec()], tool_executor=boom, max_rounds=5,
    ))
    tool_end = _events_by_kind(events)["tool_end"][0]
    assert tool_end.payload["is_error"] is True
    assert tool_end.payload["observation"].startswith("[error] get_weather")
    assert events[-1].payload["content"] == "done"


def test_none_executor_yields_unregistered_observation() -> None:
    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", _Function("get_weather", "{}"))]),
        _Resp(content="done"),
    ]
    events = _collect(run_react_loop(
        llm=_ScriptedLLM(script), messages=[{"role": "user", "content": "q"}],
        tool_specs=[_spec()], tool_executor=None, max_rounds=5,
    ))
    tool_end = _events_by_kind(events)["tool_end"][0]
    assert tool_end.payload["is_error"] is True
    assert "工具未注册" in tool_end.payload["observation"]


def test_undeclared_tool_rejected_without_touching_executor() -> None:
    """白名单：模型调用未在 tool_specs 声明的工具时直接拒绝，执行器不被触碰。"""
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "should-not-run"

    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", _Function("internal_hr_tool", "{}"))]),
        _Resp(content="done"),
    ]
    events = _collect(run_react_loop(
        llm=_ScriptedLLM(script), messages=[{"role": "user", "content": "q"}],
        tool_specs=[_spec()], tool_executor=executor, max_rounds=5,
    ))
    tool_end = _events_by_kind(events)["tool_end"][0]
    assert tool_end.payload["is_error"] is True
    assert "未在应用中声明" in tool_end.payload["observation"]
    assert "get_weather" not in tool_end.payload["observation"]  # 不回显可用清单
    assert touched == []


def test_llm_exception_propagates() -> None:
    llm = _ScriptedLLM([RuntimeError("llm 503")])
    with pytest.raises(RuntimeError, match="llm 503"):
        _collect(run_react_loop(
            llm=llm, messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()], tool_executor=lambda name, args: "ok", max_rounds=5,
        ))


def test_chat_kwargs_forwarded_and_retried_for_strict_signature() -> None:
    ctx = object()
    llm = _ScriptedLLM([_Resp(content="done")])
    _collect(run_react_loop(
        llm=llm, messages=[{"role": "user", "content": "q"}],
        tool_specs=[], tool_executor=None, max_rounds=2, chat_kwargs={"context": ctx},
    ))
    assert llm.calls[0]["kwargs"] == {"context": ctx}

    strict = _StrictLLM(_Resp(content="done"))
    events = _collect(run_react_loop(
        llm=strict, messages=[{"role": "user", "content": "q"}],
        tool_specs=[], tool_executor=None, max_rounds=2, chat_kwargs={"context": ctx},
    ))
    assert strict.calls == 1
    assert events[-1].payload["content"] == "done"


@pytest.mark.parametrize("raw,expected", [
    ({"a": 1}, {"a": 1}),
    ('{"city": "北京"}', {"city": "北京"}),
    ("not a json", {"input": "not a json"}),
    ('["list"]', {"input": '["list"]'}),
    (None, {"input": ""}),
])
def test_parse_tool_arguments(raw: Any, expected: dict) -> None:
    assert parse_tool_arguments(raw) == expected


def test_build_tool_specs_flat_nested_and_passthrough() -> None:
    spec = _spec("a")
    result = build_tool_specs([
        spec,
        {"name": "b"},
        {"function": {"name": "c", "description": "d", "parameters": {"type": "object"}}},
        {"no_name": True},
        "not-a-dict",
    ])
    assert [s.name for s in result] == ["a", "b", "c"]
    assert result[1].parameters == {"type": "object", "properties": {}}
