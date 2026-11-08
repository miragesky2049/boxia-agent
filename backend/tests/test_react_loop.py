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
    AWAITING_APPROVAL_REASON,
    BUDGET_EXCEEDED_MESSAGE,
    BUDGET_EXCEEDED_REASON,
    DEFAULT_MAX_ROUNDS_MESSAGE,
    HANDED_BACK_REASON,
    HANDED_OFF_REASON,
    UNDECLARED_TOOL_MESSAGE,
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
    return LLMToolSpec(
        name=name,
        description="天气",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    )


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
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=[_spec()],
            tool_executor=executor,
            max_rounds=5,
        )
    )

    assert [ev.kind for ev in events] == [
        "llm_start",
        "llm_end",
        "tool_start",
        "tool_end",
        "llm_start",
        "llm_end",
        "result",
    ]
    result = events[-1].payload
    assert result["content"] == "北京 20 度。"
    assert result["iterations"] == 2
    assert result["usage"] == {"prompt_tokens": 23, "completion_tokens": 10, "total_tokens": 33}
    assert result["tool_traces"][0]["observation"] == "晴，20 度"
    assert result["tool_traces"][0]["is_error"] is False

    # llm_end 的 usage 是本轮而非累计
    first_end = _events_by_kind(events)["llm_end"][0]
    assert first_end.payload["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 4,
        "total_tokens": 12,
    }

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
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=lambda name, args: "ok",
            max_rounds=3,
        )
    )
    result = events[-1].payload
    assert result["content"] == DEFAULT_MAX_ROUNDS_MESSAGE
    assert result["iterations"] == 3
    assert len(result["tool_traces"]) == 3

    events2 = _collect(
        run_react_loop(
            llm=llm,
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=lambda name, args: "ok",
            max_rounds=2,
            max_rounds_message="（execute 达到最大工具轮次）",
        )
    )
    assert events2[-1].payload["content"] == "（execute 达到最大工具轮次）"


def test_executor_exception_becomes_error_observation() -> None:
    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", _Function("get_weather", "{}"))]),
        _Resp(content="done"),
    ]

    async def boom(name: str, args: dict) -> str:
        raise RuntimeError("gateway down")

    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(script),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=boom,
            max_rounds=5,
        )
    )
    tool_end = _events_by_kind(events)["tool_end"][0]
    assert tool_end.payload["is_error"] is True
    assert tool_end.payload["observation"].startswith("[error] get_weather")
    assert events[-1].payload["content"] == "done"


def test_none_executor_yields_unregistered_observation() -> None:
    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", _Function("get_weather", "{}"))]),
        _Resp(content="done"),
    ]
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(script),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=None,
            max_rounds=5,
        )
    )
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
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(script),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=executor,
            max_rounds=5,
        )
    )
    tool_end = _events_by_kind(events)["tool_end"][0]
    assert tool_end.payload["is_error"] is True
    assert "未在应用中声明" in tool_end.payload["observation"]
    assert "get_weather" not in tool_end.payload["observation"]  # 不回显可用清单
    assert touched == []


def test_llm_exception_propagates() -> None:
    llm = _ScriptedLLM([RuntimeError("llm 503")])
    with pytest.raises(RuntimeError, match="llm 503"):
        _collect(
            run_react_loop(
                llm=llm,
                messages=[{"role": "user", "content": "q"}],
                tool_specs=[_spec()],
                tool_executor=lambda name, args: "ok",
                max_rounds=5,
            )
        )


def test_chat_kwargs_forwarded_and_retried_for_strict_signature() -> None:
    ctx = object()
    llm = _ScriptedLLM([_Resp(content="done")])
    _collect(
        run_react_loop(
            llm=llm,
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[],
            tool_executor=None,
            max_rounds=2,
            chat_kwargs={"context": ctx},
        )
    )
    assert llm.calls[0]["kwargs"] == {"context": ctx}

    strict = _StrictLLM(_Resp(content="done"))
    events = _collect(
        run_react_loop(
            llm=strict,
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[],
            tool_executor=None,
            max_rounds=2,
            chat_kwargs={"context": ctx},
        )
    )
    assert strict.calls == 1
    assert events[-1].payload["content"] == "done"


# ---------- 0074 PRD F11.1 单 run token 预算 ----------
def _tool_resp(usage: _Usage) -> _Resp:
    return _Resp(
        content="",
        tool_calls=[_ToolCall("c", _Function("get_weather", "{}"))],
        usage=usage,
        finish_reason="tool_calls",
    )


def test_budget_exceeded_stops_before_running_next_round_tools() -> None:
    """usage_base 已达预算且模型仍要调工具：工具不执行，result 标 budget_exceeded。"""
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "ok"

    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM([_tool_resp(_Usage(5, 5))]),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=executor,
            max_rounds=5,
            token_budget=100,
            usage_base={"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100},
        )
    )
    result = events[-1].payload
    assert result["finish_reason"] == BUDGET_EXCEEDED_REASON
    assert result["content"] == BUDGET_EXCEEDED_MESSAGE
    assert touched == []
    assert [ev.kind for ev in events] == ["llm_start", "llm_end", "result"]
    # 基线 + 本轮消耗都计入透出 usage
    assert result["usage"]["total_tokens"] == 110


def test_budget_not_judged_when_answer_converged() -> None:
    """已收敛（无工具调用）时不判预算：超预算的最终回答照常透出。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM([_Resp(content="最终回答", usage=_Usage(200, 100))]),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=None,
            max_rounds=5,
            token_budget=100,
        )
    )
    result = events[-1].payload
    assert result["content"] == "最终回答"
    assert result["finish_reason"] == "stop"


def test_budget_triggers_mid_loop_after_accumulated_rounds() -> None:
    """逐轮累计：第一轮 60 未超、工具执行；第二轮累计 120 ≥ 100 且仍要调工具 → 停。"""
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "ok"

    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM([_tool_resp(_Usage(40, 20)), _tool_resp(_Usage(60, 0))]),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=executor,
            max_rounds=5,
            token_budget=100,
        )
    )
    assert touched == ["get_weather"]
    result = events[-1].payload
    assert result["finish_reason"] == BUDGET_EXCEEDED_REASON
    assert result["iterations"] == 2
    assert len(result["tool_traces"]) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"a": 1}, {"a": 1}),
        ('{"city": "北京"}', {"city": "北京"}),
        ("not a json", {"input": "not a json"}),
        ('["list"]', {"input": '["list"]'}),
        (None, {"input": ""}),
    ],
)
def test_parse_tool_arguments(raw: Any, expected: dict) -> None:
    assert parse_tool_arguments(raw) == expected


def test_build_tool_specs_flat_nested_and_passthrough() -> None:
    spec = _spec("a")
    result = build_tool_specs(
        [
            spec,
            {"name": "b"},
            {"function": {"name": "c", "description": "d", "parameters": {"type": "object"}}},
            {"no_name": True},
            "not-a-dict",
        ]
    )
    assert [s.name for s in result] == ["a", "b", "c"]
    assert result[1].parameters == {"type": "object", "properties": {}}


# ---------- 0074 PRD F10（M3）：敏感工具人审门控与快照续跑 ----------
def _pending_messages(
    call_id: str = "c1", name: str = "send_email", arguments: str = '{"to": "boss"}'
) -> list[dict]:
    """构造 F10 快照续跑前置形态：末条 assistant 带未回答 tool_calls。"""
    return [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "发邮件"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
    ]


def test_approval_gate_blocks_sensitive_round_without_executing() -> None:
    """敏感调用轮整轮挂起：不执行任何工具、assistant 留在 messages、
    approval_required + result(awaiting_approval)。"""
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", _Function("send_email", '{"to": "boss"}'))],
                finish_reason="tool_calls",
            ),
        ]
    )
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "ok"

    messages = [{"role": "user", "content": "发邮件"}]
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=[_spec("get_weather"), _spec("send_email")],
            tool_executor=executor,
            max_rounds=5,
            sensitive_tool_names={"send_email"},
        )
    )

    kinds = [ev.kind for ev in events]
    assert kinds == ["llm_start", "llm_end", "approval_required", "result"]
    assert touched == []
    approval = events[2].payload
    assert approval["awaiting_calls"][0]["id"] == "c1"
    assert approval["pending_tool_calls"][0]["name"] == "send_email"
    result = events[-1].payload
    assert result["finish_reason"] == AWAITING_APPROVAL_REASON
    assert result["content"] == ""
    # 快照前提：assistant(tool_calls) 已入 messages
    assert messages[-1]["role"] == "assistant" and messages[-1]["tool_calls"]


def test_approval_gate_blocks_whole_mixed_round() -> None:
    """同轮混合敏感/非敏感调用：非敏感也不先执行（整轮语义，快照一致）。"""
    llm = _ScriptedLLM(
        [
            _Resp(
                tool_calls=[
                    _ToolCall("c1", _Function("get_weather", "{}")),
                    _ToolCall("c2", _Function("send_email", "{}")),
                ],
                finish_reason="tool_calls",
            ),
        ]
    )
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "ok"

    events = _collect(
        run_react_loop(
            llm=llm,
            messages=[{"role": "user", "content": "查天气再发邮件"}],
            tool_specs=[_spec("get_weather"), _spec("send_email")],
            tool_executor=executor,
            max_rounds=5,
            sensitive_tool_names={"send_email"},
        )
    )
    assert touched == []
    approval = next(ev for ev in events if ev.kind == "approval_required").payload
    assert [c["id"] for c in approval["pending_tool_calls"]] == ["c1", "c2"]
    assert [c["id"] for c in approval["awaiting_calls"]] == ["c2"]


def test_approval_resume_drains_approved_round_without_extra_llm_start() -> None:
    """批准续跑：第 0 轮直接排空快照调用（不再请求 LLM），批准后不再门控。"""
    llm = _ScriptedLLM([_Resp(content="已发送并总结。", finish_reason="stop")])
    touched: list[tuple[str, dict]] = []

    def executor(name: str, args: dict) -> str:
        touched.append((name, args))
        return "邮件已送达"

    messages = _pending_messages()
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=[_spec("send_email")],
            tool_executor=executor,
            max_rounds=5,
            sensitive_tool_names={"send_email"},
            approved_call_ids={"c1"},
        )
    )

    kinds = [ev.kind for ev in events]
    # 排空轮无 llm_start；续跑轮 iteration 从 2 起（快照轮是第 1 轮）
    assert kinds == ["tool_start", "tool_end", "llm_start", "llm_end", "result"]
    assert touched == [("send_email", {"to": "boss"})]
    assert events[2].payload["iteration"] == 2
    tool_end = events[1].payload
    assert tool_end["observation"] == "邮件已送达" and tool_end["is_error"] is False
    assert events[-1].payload["content"] == "已发送并总结。"
    # 收敛轮不回填 assistant：排空后 tool 响应即末条
    assert messages[-1]["role"] == "tool"


def test_approval_resume_drains_rejected_round_as_error_observation() -> None:
    """拒绝续跑：不触达执行器，回灌带理由的拒绝 observation（is_error），模型收尾。"""
    llm = _ScriptedLLM([_Resp(content="好的，已按现有信息回答。", finish_reason="stop")])
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "不应该被执行"

    messages = _pending_messages()
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=[_spec("send_email")],
            tool_executor=executor,
            max_rounds=5,
            sensitive_tool_names={"send_email"},
            rejected_call_ids={"c1"},
            rejection_comment="不要打扰老板",
        )
    )

    assert touched == []
    tool_end = next(ev for ev in events if ev.kind == "tool_end").payload
    assert tool_end["is_error"] is True
    assert "用户拒绝了该工具调用" in tool_end["observation"]
    assert "不要打扰老板" in tool_end["observation"]
    assert events[-1].payload["content"] == "好的，已按现有信息回答。"


def test_approval_resume_approved_call_still_whitelisted() -> None:
    """批准集合只解除人审门控：白名单校验仍在排空阶段生效。"""
    llm = _ScriptedLLM([_Resp(content="收到。", finish_reason="stop")])

    def executor(name: str, args: dict) -> str:
        raise AssertionError("未声明工具不得触达执行器")

    events = _collect(
        run_react_loop(
            llm=llm,
            messages=_pending_messages(name="drop_table"),
            tool_specs=[_spec("send_email")],
            tool_executor=executor,
            max_rounds=5,
            sensitive_tool_names={"send_email"},
            approved_call_ids={"c1"},
        )
    )
    tool_end = next(ev for ev in events if ev.kind == "tool_end").payload
    assert tool_end["is_error"] is True
    assert tool_end["observation"] == UNDECLARED_TOOL_MESSAGE.format(name="drop_table")


def test_approval_budget_exceeded_precedes_gate() -> None:
    """预算触顶在挂起门控之前判定：超界轮不产生 approval_required、不落 assistant 消息。"""
    llm = _ScriptedLLM(
        [
            _Resp(
                tool_calls=[_ToolCall("c1", _Function("send_email", "{}"))],
                usage=_Usage(prompt_tokens=100, completion_tokens=100),
                finish_reason="tool_calls",
            ),
        ]
    )
    messages = [{"role": "user", "content": "发邮件"}]
    events = _collect(
        run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=[_spec("send_email")],
            tool_executor=lambda name, args: "ok",
            max_rounds=5,
            token_budget=10,
            sensitive_tool_names={"send_email"},
        )
    )
    assert not any(ev.kind == "approval_required" for ev in events)
    result = events[-1].payload
    assert result["finish_reason"] == BUDGET_EXCEEDED_REASON
    assert messages[-1]["role"] == "user"


# ---------- M4 PRD F14.9（T-c6）：接管 handoff 轮级短路 ----------
def test_handoff_gate_short_circuits_round() -> None:
    """命中 handoff 声明工具：整轮不执行（含同轮其余调用）、发 handoff 事件，
    result 以 handed_off 收尾并携带 handoff 载荷；assistant(tool_calls) 留存
    与审批挂起轮同语义（当轮正文不作最终回答）。"""
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "不应该被执行"

    messages = [{"role": "user", "content": "帮我订票"}]
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(
                        content="",
                        tool_calls=[
                            _ToolCall("c1", _Function("get_weather", "{}")),
                            _ToolCall("c2", _Function("agent_expert", '{"question":"帮我订票"}')),
                        ],
                        usage=_Usage(1, 1),
                        finish_reason="tool_calls",
                    ),
                ]
            ),
            messages=messages,
            tool_specs=[_spec("get_weather"), _spec("agent_expert")],
            tool_executor=executor,
            max_rounds=5,
            handoff_targets={"agent_expert": "app-2"},
        )
    )
    assert [ev.kind for ev in events] == ["llm_start", "llm_end", "handoff", "result"]
    assert touched == []
    handoff = events[2].payload
    assert handoff == {
        "iteration": 1,
        "tool_round": 0,
        "tool_name": "agent_expert",
        "tool_call_id": "c2",
        "arguments_raw": '{"question":"帮我订票"}',
        "application_id": "app-2",
        "returned": False,
    }
    result = events[-1].payload
    assert result["finish_reason"] == HANDED_OFF_REASON
    assert result["content"] == ""
    assert result["handoff"] == handoff
    assert messages[-1]["role"] == "assistant" and messages[-1]["tool_calls"]


def test_hand_back_gate_marks_returned() -> None:
    """目标侧 hand_back 伪工具命中：returned=True、application_id 空、
    finish_reason=handed_back（归属应用由消费方按会话路由态解析）。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(
                        content="",
                        tool_calls=[_ToolCall("c1", _Function("hand_back", "{}"))],
                        usage=_Usage(1, 1),
                        finish_reason="tool_calls",
                    ),
                ]
            ),
            messages=[{"role": "user", "content": "已办结"}],
            tool_specs=[_spec("hand_back")],
            tool_executor=None,
            max_rounds=5,
            handoff_targets={},
            hand_back_name="hand_back",
        )
    )
    assert [ev.kind for ev in events] == ["llm_start", "llm_end", "handoff", "result"]
    handoff = events[2].payload
    assert handoff["tool_name"] == "hand_back"
    assert handoff["application_id"] is None
    assert handoff["returned"] is True
    assert events[-1].payload["finish_reason"] == HANDED_BACK_REASON


def test_handoff_gate_precedes_approval_gate() -> None:
    """同轮混合敏感调用与接管调用：接管门在前，不产生 approval_required 挂起。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(
                        tool_calls=[
                            _ToolCall("c1", _Function("send_email", "{}")),
                            _ToolCall("c2", _Function("agent_expert", "{}")),
                        ],
                        usage=_Usage(1, 1),
                        finish_reason="tool_calls",
                    ),
                ]
            ),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec("send_email"), _spec("agent_expert")],
            tool_executor=lambda name, args: "ok",
            max_rounds=5,
            sensitive_tool_names={"send_email"},
            handoff_targets={"agent_expert": "app-2"},
        )
    )
    assert not any(ev.kind == "approval_required" for ev in events)
    assert any(ev.kind == "handoff" for ev in events)
    assert events[-1].payload["finish_reason"] == HANDED_OFF_REASON


def test_handoff_not_hit_keeps_result_payload_shape_baseline() -> None:
    """未命中接管（或调用方未传接管参数）：result 载荷不出现 handoff 键，
    与改造前逐字段一致。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(content="直接回答", usage=_Usage(1, 1), finish_reason="stop"),
                ]
            ),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=None,
            max_rounds=5,
        )
    )
    result = events[-1].payload
    assert set(result.keys()) == {
        "content",
        "reasoning_content",
        "tool_traces",
        "iterations",
        "usage",
        "finish_reason",
    }
    assert not any(ev.kind == "handoff" for ev in events)

    events2 = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(content="直接回答", usage=_Usage(1, 1), finish_reason="stop"),
                ]
            ),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec()],
            tool_executor=None,
            max_rounds=5,
            handoff_targets={"agent_expert": "app-2"},
        )
    )
    assert "handoff" not in events2[-1].payload
    assert events2[-1].payload["finish_reason"] == "stop"


def test_handoff_hit_on_second_round_after_normal_tools() -> None:
    """前轮正常工具照常执行，接管命中轮短路：tool_traces 只含前轮，iterations=2。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM(
                [
                    _Resp(
                        tool_calls=[_ToolCall("c1", _Function("get_weather", "{}"))],
                        usage=_Usage(1, 1),
                        finish_reason="tool_calls",
                    ),
                    _Resp(
                        tool_calls=[_ToolCall("c2", _Function("agent_expert", "{}"))],
                        usage=_Usage(1, 1),
                        finish_reason="tool_calls",
                    ),
                ]
            ),
            messages=[{"role": "user", "content": "q"}],
            tool_specs=[_spec("get_weather"), _spec("agent_expert")],
            tool_executor=lambda name, args: "晴",
            max_rounds=5,
            handoff_targets={"agent_expert": "app-2"},
        )
    )
    assert [ev.kind for ev in events] == [
        "llm_start",
        "llm_end",
        "tool_start",
        "tool_end",
        "llm_start",
        "llm_end",
        "handoff",
        "result",
    ]
    result = events[-1].payload
    assert result["iterations"] == 2
    assert [t["name"] for t in result["tool_traces"]] == ["get_weather"]
    assert result["handoff"]["tool_call_id"] == "c2"


def test_handoff_gate_covers_snapshot_resume_round() -> None:
    """快照续跑轮（第 0 轮不请求 LLM）同样受接管门控：不排空、再短路。"""
    events = _collect(
        run_react_loop(
            llm=_ScriptedLLM([_Resp(content="不应该被调用", finish_reason="stop")]),
            messages=_pending_messages(
                call_id="c1", name="agent_expert", arguments='{"question":"x"}'
            ),
            tool_specs=[_spec("agent_expert")],
            tool_executor=lambda name, args: "ok",
            max_rounds=5,
            handoff_targets={"agent_expert": "app-2"},
        )
    )
    assert [ev.kind for ev in events] == ["handoff", "result"]
    assert events[-1].payload["finish_reason"] == HANDED_OFF_REASON
