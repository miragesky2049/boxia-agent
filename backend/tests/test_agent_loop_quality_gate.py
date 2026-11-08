"""M4-d PRD F19.2：agent_loop 收敛后运行时质量门单测。

门语义：judge 打分 score ≥ passScore 视为通过（阈值判定归本消费方，不受内核
默认 7 兜底干扰）；不达标且重生未超 maxRegen → critique 作 user 消息追加、
再跑一次 execute；judge 自身 usage 计入本 run usage/tokenBudget；达上限仍不
过 → fail-open 放行（U13）；judge 调用异常 → fail-open 放行原答案并标记。
审批挂起轮/接管轮/预算触顶轮/子 run（C8）/空答案轮不付 judge 成本。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from internal.domain.canvas.expression import EvalContext
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.agent_loop import AgentLoopNodeHandler

# JUDGE_SYSTEM_PROMPT 首句固定标记：fake 据此区分 judge 调用与 execute 调用
_JUDGE_MARKER = "你是严格的回答质量评审员"
# 深度模式 plan/reflect 阶段默认提示词首句标记（与 agent_loop 常量同源）
_PLAN_MARKER = "你是任务规划器"
_REFLECT_MARKER = "你是质量评审"

_JUDGE_USAGE = {"prompt": 4, "completion": 2}


class _Usage:
    def __init__(self, prompt: int = 1, completion: int = 1) -> None:
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
    def __init__(
        self, content: str, tool_calls: list | None = None, usage: _Usage | None = None
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage or _Usage()


class _ScriptedModel:
    """LLMServiceAdapter 形态替身：chat 签名显式要求 model，验证消费端 judge 模型绑定。

    exec/judge/plan/reflect 各自按脚本队列消费；队列耗尽即断言"多付了一次调用"；
    队列元素允许直接放异常实例（模拟该次调用传输层异常）；
    raise_on_judge 模拟 judge 服务异常（验收 7 的 fail-open 分支）。
    """

    def __init__(
        self,
        exec_script: list[_Resp | Exception],
        judge_script: list[_Resp | Exception],
        *,
        raise_on_judge: bool = False,
        plan_script: list[_Resp] | None = None,
        reflect_script: list[_Resp] | None = None,
    ) -> None:
        self._exec = list(exec_script)
        self._judge = list(judge_script)
        self._plan = list(plan_script or [])
        self._reflect = list(reflect_script or [])
        self.raise_on_judge = raise_on_judge
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: Any = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        context: Any = None,
        **kwargs: Any,
    ) -> _Resp:
        text0 = str(messages[0].get("content") or "")
        if _JUDGE_MARKER in text0:
            kind = "judge"
        elif _PLAN_MARKER in text0:
            kind = "plan"
        elif _REFLECT_MARKER in text0:
            kind = "reflect"
        else:
            kind = "exec"
        self.calls.append({"kind": kind, "model": model, "messages": messages})
        if kind == "judge" and self.raise_on_judge:
            raise ConnectionError("judge 服务暂不可用")
        queue = {
            "judge": self._judge,
            "plan": self._plan,
            "reflect": self._reflect,
            "exec": self._exec,
        }[kind]
        assert queue, f"{kind} 脚本队列已空：门不应再发该阶段调用"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def plan_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["kind"] == "plan"]

    def reflect_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["kind"] == "reflect"]

    def judge_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["kind"] == "judge"]

    def exec_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["kind"] == "exec"]


def _judge_resp(score: int, critique: str = "", *, passed: Any = ...) -> _Resp:
    """judge 结构化输出：passed 键默认缺省（走内核 score>=7 兜底），显式传入可覆盖。

    门的判定始终按消费方 passScore（F19.2），与 payload.passed 的关系由用例锁定。
    """
    payload: dict[str, Any] = {"score": score, "critique": critique}
    if passed is not ...:
        payload["passed"] = passed
    return _Resp(
        content=json.dumps(payload, ensure_ascii=False),
        usage=_Usage(_JUDGE_USAGE["prompt"], _JUDGE_USAGE["completion"]),
    )


class _FakeAgentTool:
    """AgentToolService 端口替身：接管声明工具只需合成成功，不进执行器分派。"""

    async def describe(
        self,
        application_id: str,
        chain: list[str],
        *,
        tool_name: str | None = None,
        description: str | None = None,
    ) -> dict | None:
        return {
            "name": tool_name or f"agent_{application_id[:8]}",
            "description": f"把问题移交专家。专长：{description or '默认'}",
            "parameters": {"type": "object", "properties": {}},
        }


def _make_ctx(
    services: ServiceRegistry,
    config: dict,
    runtime_input: dict | None = None,
    events: list[tuple[str, dict]] | None = None,
) -> NodeContext:
    async def _emit(etype: str, payload: dict) -> None:
        if events is not None:
            events.append((etype, payload))

    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="agent_1",
        node_type=NodeType.AGENT_LOOP.value,
        inputs={},
        config=config,
        env=env,
        services=services,
        eval_context=EvalContext(
            input=runtime_input
            if runtime_input is not None
            else {"react_only": True, "input": "问题"},
            node_outputs={},
            globals={},
            env={},
        ),
        emit_event=_emit,
    )


def _gate_config(quality_gate: dict | None = None, **extra: Any) -> dict:
    config: dict[str, Any] = {"modleName": "m", "systemPrompt": "S"}
    if quality_gate is not None:
        config["qualityGate"] = quality_gate
    config.update(extra)
    return config


def _run(
    llm: _ScriptedModel,
    config: dict,
    runtime_input: dict | None = None,
    *,
    services_extra: dict | None = None,
    events: list[tuple[str, dict]] | None = None,
) -> Any:
    services = ServiceRegistry({"llm": llm, **(services_extra or {})})
    ctx = _make_ctx(services, config, runtime_input, events)
    return asyncio.run(AgentLoopNodeHandler().run(ctx))


# ---------- 门关闭/缺失：与基线逐字段一致 ----------


def test_gate_absent_keeps_baseline_outputs_and_frames() -> None:
    events: list[tuple[str, dict]] = []
    llm = _ScriptedModel([_Resp(content="回答A", usage=_Usage(10, 5))], [])
    result = _run(llm, _gate_config(), events=events)

    assert set(result.outputs) == {"output", "plan", "reflect_history", "model"}
    assert llm.judge_calls() == []
    assert [etype for etype, _ in events].count("judge") == 0


def test_gate_disabled_skips_judge() -> None:
    llm = _ScriptedModel([_Resp(content="回答A")], [_judge_resp(1)])
    result = _run(llm, _gate_config({"enabled": False, "passScore": 8}))
    assert "judge" not in result.outputs
    assert llm.judge_calls() == []


# ---------- 门开启：判定/重生/放行 ----------


def test_gate_pass_first_attempt_additive_outcome() -> None:
    events: list[tuple[str, dict]] = []
    llm = _ScriptedModel(
        [_Resp(content="回答A", usage=_Usage(10, 5))],
        [_judge_resp(8, "")],
    )
    result = _run(
        llm,
        _gate_config({"enabled": True, "passScore": 7}),
        {"react_only": True, "input": "北京天气"},
        events=events,
    )

    assert result.outputs["output"] == "回答A"
    assert result.outputs["judge"] == {"score": 8, "passed": True, "attempts": 1}
    assert len(llm.exec_calls()) == 1 and len(llm.judge_calls()) == 1
    # judge usage 计入本 run 预算（15+6）
    assert result.usage["total_tokens"] == 15 + _JUDGE_USAGE["prompt"] + _JUDGE_USAGE["completion"]
    judge_call = llm.judge_calls()[0]
    # judgeModel 缺省绑定答题模型；问题与回答进 judge 上下文
    assert judge_call["model"] == "m"
    joined = json.dumps(judge_call["messages"], ensure_ascii=False)
    assert "北京天气" in joined and "回答A" in joined
    trace = [p for e, p in events if e == "judge"]
    assert trace[0]["score"] == 8 and trace[0]["passed"] is True and trace[0]["attempts"] == 1


def test_gate_pass_score_overrides_kernel_default_and_payload() -> None:
    """passScore=9 时按消费方分数判定：score=9 过（哪怕模型说 passed=false）；score=7 不过。"""
    llm = _ScriptedModel(
        [_Resp(content="回答A")],
        [_judge_resp(9, "轻微瑕疵", passed=False)],
    )
    result = _run(llm, _gate_config({"enabled": True, "passScore": 9, "maxRegen": 0}))
    assert result.outputs["judge"] == {"score": 9, "passed": True, "attempts": 1}
    assert len(llm.exec_calls()) == 1

    llm2 = _ScriptedModel(
        [_Resp(content="回答B")],
        # 内核缺省兜底 7 会判过，消费方 passScore=9 必须判不过 → maxRegen 0 则只跑一次 judge
        [_judge_resp(7, "未达线", passed=True)],
    )
    result2 = _run(llm2, _gate_config({"enabled": True, "passScore": 9, "maxRegen": 0}))
    assert result2.outputs["judge"] == {"score": 7, "passed": False, "attempts": 1}
    assert len(llm2.exec_calls()) == 1


def test_gate_fail_then_regen_pass() -> None:
    llm = _ScriptedModel(
        [_Resp(content="初始回答"), _Resp(content="修正回答")],
        [_judge_resp(5, "未引用知识库出处"), _judge_resp(9, "")],
    )
    result = _run(
        llm,
        _gate_config({"enabled": True, "passScore": 8, "maxRegen": 1}),
        {"react_only": True, "input": "退款政策是什么"},
    )

    assert result.outputs["output"] == "修正回答"
    assert result.outputs["judge"] == {"score": 9, "passed": True, "attempts": 2}
    regen_messages = llm.exec_calls()[1]["messages"]
    critiqued = [
        m for m in regen_messages if m.get("role") == "user" and "质量门" in str(m.get("content"))
    ]
    assert critiqued and "未引用知识库出处" in critiqued[0]["content"]


def test_gate_fail_open_at_max_regen() -> None:
    """重生用尽仍不达标 → fail-open 放行重生稿并留档最终判定（U13/验收 7）。"""
    llm = _ScriptedModel(
        [_Resp(content="初稿"), _Resp(content="重生稿")],
        [_judge_resp(3, "仍缺出处"), _judge_resp(4, "还是缺")],
    )
    result = _run(llm, _gate_config({"enabled": True, "passScore": 7, "maxRegen": 1}))
    assert result.outputs["output"] == "重生稿"
    assert result.outputs["judge"] == {"score": 4, "passed": False, "attempts": 2}
    assert len(llm.exec_calls()) == 2 and len(llm.judge_calls()) == 2


def test_gate_max_regen_zero_single_judge() -> None:
    llm = _ScriptedModel([_Resp(content="原答案")], [_judge_resp(2, "太差")])
    result = _run(llm, _gate_config({"enabled": True, "passScore": 7, "maxRegen": 0}))
    assert result.outputs["output"] == "原答案"
    assert result.outputs["judge"] == {"score": 2, "passed": False, "attempts": 1}
    assert len(llm.exec_calls()) == 1


def test_gate_judge_error_fail_open_with_mark() -> None:
    events: list[tuple[str, dict]] = []
    llm = _ScriptedModel([_Resp(content="原答案")], [], raise_on_judge=True)
    result = _run(llm, _gate_config({"enabled": True}), events=events)

    assert result.outputs["output"] == "原答案"
    assert result.outputs["judge"] == {
        "score": None,
        "passed": False,
        "attempts": 1,
        "error": True,
    }
    assert len(llm.exec_calls()) == 1
    trace = [p for e, p in events if e == "judge"]
    assert trace[0]["error"] is True


def test_gate_judge_model_binding_and_attribution() -> None:
    events: list[tuple[str, dict]] = []
    llm = _ScriptedModel([_Resp(content="回答A")], [_judge_resp(9)])
    result = _run(
        llm,
        _gate_config({"enabled": True, "judgeModel": "judge-m", "passScore": 7}),
        events=events,
    )
    assert llm.exec_calls()[0]["model"] == "m"
    assert llm.judge_calls()[0]["model"] == "judge-m"
    assert result.outputs["judge"]["passed"] is True
    trace = [p for e, p in events if e == "judge"]
    assert trace[0]["model"] == "judge-m"


def test_gate_context_refs_from_tool_observations() -> None:
    def executor(name: str, args: dict) -> str:
        return "巴黎当前气温 15 度（来源：气象库）"

    llm = _ScriptedModel(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", '{"city":"巴黎"}')]),
            _Resp(content="回答：15 度"),
        ],
        [_judge_resp(8)],
    )
    config = _gate_config(
        {"enabled": True, "rubric": "事实性以参考资料为准"},
        tools=[
            {
                "name": "get_weather",
                "description": "天气",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    )
    _run(
        llm,
        config,
        {"react_only": True, "input": "巴黎天气"},
        services_extra={"tool_executor": executor},
    )
    judge_messages = json.dumps(llm.judge_calls()[0]["messages"], ensure_ascii=False)
    assert "参考资料" in judge_messages and "巴黎当前气温 15 度" in judge_messages


# ---------- 跳过条件：不付 judge 成本 ----------


def test_gate_skipped_when_awaiting_approval() -> None:
    def executor(name: str, args: dict) -> str:
        raise AssertionError("挂起轮不得执行工具")

    llm = _ScriptedModel(
        [_Resp(content="", tool_calls=[_ToolCall("c1", "send_email", "{}")])],
        [_judge_resp(1)],
    )
    config = _gate_config(
        {"enabled": True},
        tools=[
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        sensitiveTools=[{"name": "send_email"}],
    )
    result = _run(
        llm,
        config,
        {"react_only": True, "input": "发邮件"},
        services_extra={"tool_executor": executor},
    )
    assert result.outputs["awaiting_approval"] is True
    assert llm.judge_calls() == []


def test_gate_skipped_on_handoff_round() -> None:
    llm = _ScriptedModel(
        [_Resp(content="", tool_calls=[_ToolCall("c1", "agent_7b2e3d4c", '{"question":"订票"}')])],
        [_judge_resp(1)],
    )
    config = _gate_config(
        {"enabled": True},
        subAgents=[
            {
                "applicationId": "7b2e3d4c-0000-0000-0000-000000000002",
                "mode": "handoff",
                "description": "票务",
            }
        ],
    )
    result = _run(
        llm,
        config,
        {"react_only": True, "input": "订票"},
        services_extra={"agent_tool": _FakeAgentTool()},
    )
    assert result.outputs["finish_reason"] == "handed_off"
    assert llm.judge_calls() == []


def test_gate_skipped_on_budget_exceeded() -> None:
    def executor(name: str, args: dict) -> str:
        return "观测"

    # 首轮 usage 已超预算且还有工具待答：内核以固定文案收尾（budget_hit），门不再追评
    llm = _ScriptedModel(
        [
            _Resp(
                content="", tool_calls=[_ToolCall("c1", "get_weather", "{}")], usage=_Usage(30, 20)
            )
        ],
        [_judge_resp(1)],
    )
    config = _gate_config({"enabled": True}, tokenBudget=1)
    config["tools"] = [
        {
            "name": "get_weather",
            "description": "天气",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    result = _run(
        llm, config, {"react_only": True, "input": "q"}, services_extra={"tool_executor": executor}
    )
    assert result.outputs.get("finish_reason") == "budget_exceeded"
    assert "judge" not in result.outputs
    assert llm.judge_calls() == []


def test_gate_skipped_for_sub_run() -> None:
    """C8：委派/工作流子 run 不触发质量门，防成本放大。"""
    llm = _ScriptedModel([_Resp(content="子run回答")], [_judge_resp(1)])
    runtime_input = {"react_only": True, "input": "q", "workflow_chain": ["parent-app"]}
    result = _run(llm, _gate_config({"enabled": True}), runtime_input)
    assert llm.judge_calls() == []
    assert "judge" not in result.outputs


def test_gate_skipped_on_empty_answer() -> None:
    llm = _ScriptedModel([_Resp(content="")], [_judge_resp(1)])
    _run(llm, _gate_config({"enabled": True}))
    assert llm.judge_calls() == []


def test_gate_budget_exhausted_stops_regen() -> None:
    """judge 自身 usage 计入 tokenBudget：预算耗尽即不再重生（终判留档 attempts=1）。"""
    llm = _ScriptedModel(
        [_Resp(content="初稿", usage=_Usage(30, 20))],
        [
            _Resp(
                content=json.dumps({"score": 2, "critique": "差"}),
                usage=_Usage(25, 25),
            )
        ],
    )
    config = _gate_config({"enabled": True, "maxRegen": 1}, tokenBudget=100)
    result = _run(llm, config)
    assert result.outputs["judge"] == {"score": 2, "passed": False, "attempts": 1}
    assert len(llm.exec_calls()) == 1


def test_gate_tolerates_dirty_config_bounds() -> None:
    """运行侧容错：passScore/maxRegen 越界回配置面默认（7/1），与 agent_config 同口径。"""
    llm = _ScriptedModel(
        [_Resp(content="初稿"), _Resp(content="重生稿")],
        [_judge_resp(6, "略差"), _judge_resp(4, "仍差")],
    )
    result = _run(llm, _gate_config({"enabled": True, "passScore": 999, "maxRegen": 5}))
    assert result.outputs["output"] == "重生稿"
    assert result.outputs["judge"] == {"score": 4, "passed": False, "attempts": 2}


# ---------- 批末 review 修正（P1-1 / P1-2）：重生途中的通道自洽 ----------


def test_gate_regen_awaiting_advances_snapshot_round() -> None:
    """P1-1：深度模式重生途中触发审批挂起时，approval/snapshot 的 reflect_round
    必须等于真实重生轮次——批准续跑以该轮为起点，恒 0 会复跑已完成轮次并放大成本。"""

    def executor(name: str, args: dict) -> str:
        raise AssertionError("挂起轮不得执行工具")

    llm = _ScriptedModel(
        [
            _Resp(content="初稿"),
            _Resp(content="", tool_calls=[_ToolCall("c1", "send_email", "{}")]),
        ],
        [_judge_resp(3, "仍需补充")],
        plan_script=[
            _Resp(content='{"tasks": [{"id": "t1", "goal": "答一问", "acceptance": "ok"}]}')
        ],
        reflect_script=[_Resp(content='{"done": true, "critique": "", "suggestion": ""}')],
    )
    config = _gate_config(
        {"enabled": True, "passScore": 7, "maxRegen": 1},
        tools=[
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        sensitiveTools=[{"name": "send_email"}],
    )
    result = _run(
        llm,
        config,
        {"react_only": False, "input": "发邮件"},
        services_extra={"tool_executor": executor},
    )

    assert result.outputs["awaiting_approval"] is True
    assert result.outputs["approval"]["reflect_round"] == 1
    assert result.outputs["snapshot"]["reflect_round"] == 1
    # 门结论作废走审批原通道：不带 judge 键，重生确实发生过一次
    assert "judge" not in result.outputs
    assert len(llm.exec_calls()) == 2 and len(llm.judge_calls()) == 1


def test_gate_regen_execute_error_keeps_original_answer() -> None:
    """P1-2：重生 execute 异常时内核回 "[execute error] ..." 桩，不得顶掉原答案——
    视同重生失败，保留最后一次有效判定 fail-open 放行。"""
    llm = _ScriptedModel(
        [_Resp(content="原答案"), ConnectionError("上游超时")],
        [_judge_resp(3, "缺出处")],
    )
    result = _run(llm, _gate_config({"enabled": True, "passScore": 7, "maxRegen": 1}))

    assert result.outputs["output"] == "原答案"
    assert result.outputs["judge"] == {"score": 3, "passed": False, "attempts": 1}
    assert len(llm.exec_calls()) == 2 and len(llm.judge_calls()) == 1
