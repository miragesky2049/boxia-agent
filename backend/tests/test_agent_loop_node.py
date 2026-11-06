"""A6：Agent 循环节点 plan/execute/reflect 三阶段协议单测。"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from internal.domain.agent.run_context import AgentRunContext
from internal.domain.canvas.expression import EvalContext
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.agent_loop import AgentLoopNodeHandler


class _Usage:
    def __init__(self, prompt: int = 5, completion: int = 5) -> None:
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
    def __init__(self, content: str, tool_calls: list | None = None, usage: _Usage | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.usage = usage or _Usage()


class _ScriptedLLM:
    """按脚本顺序返回响应，记录每次调用参数。"""

    def __init__(self, script: list[_Resp]) -> None:
        self._script = script
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, response_format=None, **kwargs) -> _Resp:
        self.calls.append({
            "messages": messages,
            "tools": tools,
            "response_format": response_format,
            "model": kwargs.get("model"),
            "context": kwargs.get("context"),
        })
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return self._script[idx]


def _make_ctx(services: ServiceRegistry, config: dict, user_input: str) -> NodeContext:
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
    )


def test_agent_loop_plan_execute_reflect_done_first_pass() -> None:
    """Plan 输出任务清单，Execute 首轮回答，Reflect 直接 done=true。"""
    script = [
        # PLAN
        _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "回答问题", "acceptance": "简短"}]}), usage=_Usage(10, 5)),
        # EXECUTE（第一轮即最终答案）
        _Resp(content="北京今天 20 度。", usage=_Usage(20, 10)),
        # REFLECT
        _Resp(content=json.dumps({"done": True, "critique": "", "suggestion": ""}), usage=_Usage(5, 2)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm})

    ctx = _make_ctx(services, {"modleName": "m", "systemPrompt": "你是助手"}, "北京天气怎么样")
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "北京今天 20 度。"
    assert len(result.outputs["plan"]) == 1
    assert result.outputs["plan"][0]["id"] == "t1"
    assert result.outputs["reflect_history"][0]["done"] is True
    assert len(llm.calls) == 3
    # PLAN 与 REFLECT 都要求 JSON
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    assert llm.calls[2]["response_format"] == {"type": "json_object"}
    # usage 累加
    assert result.usage["total_tokens"] == (15 + 30 + 7)


def test_agent_loop_reflect_not_done_then_re_execute() -> None:
    """Reflect 第一轮 done=false 并给出 suggestion → 再跑一次 execute + reflect。"""
    script = [
        # PLAN
        _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "算和", "acceptance": "给出数字"}]}), usage=_Usage(5, 2)),
        # EXECUTE 1
        _Resp(content="1+2=4（错）", usage=_Usage(10, 3)),
        # REFLECT 1：指出错误
        _Resp(content=json.dumps({"done": False, "critique": "结果不对", "suggestion": "重新计算"}), usage=_Usage(3, 2)),
        # EXECUTE 2
        _Resp(content="1+2=3", usage=_Usage(10, 3)),
        # REFLECT 2
        _Resp(content=json.dumps({"done": True, "critique": ""}), usage=_Usage(3, 1)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm})

    ctx = _make_ctx(services, {"modleName": "m"}, "算 1+2")
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "1+2=3"
    assert len(result.outputs["reflect_history"]) == 2
    # 第二轮 execute 的 messages 里应包含上一轮的 critique
    second_execute_messages = llm.calls[3]["messages"]
    assert any(
        "上一轮结果未达标" in m.get("content", "") and "重新计算" in m.get("content", "")
        for m in second_execute_messages
    )


def test_agent_loop_with_tool_call_in_execute_phase() -> None:
    """Execute 阶段 LLM 返回 tool_calls，工具被执行后回灌。"""
    tool_calls_seen: list[tuple[str, dict]] = []

    def _tool_executor(name: str, args: dict) -> str:
        tool_calls_seen.append((name, args))
        return "晴，20 度"

    script = [
        # PLAN
        _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "查天气"}]}), usage=_Usage(3, 1)),
        # EXECUTE 第一轮：tool_call
        _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')], usage=_Usage(8, 4)),
        # EXECUTE 第二轮：拿到 tool 结果后最终回答
        _Resp(content="北京 20 度。", usage=_Usage(15, 6)),
        # REFLECT
        _Resp(content=json.dumps({"done": True}), usage=_Usage(3, 1)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    ctx = _make_ctx(services, {
        "modleName": "m",
        "tools": [{"name": "get_weather", "description": "天气", "parameters": {"type": "object", "properties": {}}}],
    }, "北京天气")
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "北京 20 度。"
    assert len(tool_calls_seen) == 1
    assert tool_calls_seen[0][0] == "get_weather"
    # execute 第二轮 messages 里包含 tool 角色 + tool 结果
    execute_round2_messages = llm.calls[2]["messages"]
    assert any(m["role"] == "tool" and m["content"] == "晴，20 度" for m in execute_round2_messages)


def test_agent_loop_stub_when_llm_not_registered() -> None:
    """services 无 llm 时返回 stub，不抛异常。"""
    services = ServiceRegistry()
    ctx = _make_ctx(services, {"modleName": "m"}, "你好")
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert "[AgentLoop stub]" in result.outputs["output"]


# ---------- 20261106 P3：chat 兼容通道（react_only/history/override/context 透传）----------
def _make_runtime_ctx(
    services: ServiceRegistry,
    config: dict,
    runtime_input: dict,
    emit=None,
) -> NodeContext:
    """构造带 eval_context.input 的节点上下文，模拟 chat 驱动画布运行。

    inputs 刻意不含 "input" 键，验证问题文本回退到运行期入参。
    """
    env = RuntimeEnv(
        tenant_id=uuid4(), user_id=None, run_id=uuid4(),
        thread_id="test", application_id=uuid4(),
    )
    return NodeContext(
        node_id="agent_1",
        node_type=NodeType.AGENT_LOOP.value,
        inputs={},
        config=config,
        env=env,
        services=services,
        eval_context=EvalContext(input=runtime_input, node_outputs={}, globals={}, env={}),
        emit_event=emit,
    )


def test_agent_loop_react_only_skips_plan_and_reflect() -> None:
    """react_only：只跑一次 execute，不调 plan/reflect LLM，也不产生其 trace 事件。"""
    events: list[tuple[str, dict]] = []

    async def _emit(etype: str, payload: dict) -> None:
        events.append((etype, payload))

    script = [_Resp(content="回答结束。", usage=_Usage(2, 1))]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm})

    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {"react_only": True, "input": "你好"},
        emit=_emit,
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "回答结束。"
    assert result.outputs["plan"] == []
    assert result.outputs["reflect_history"] == []
    # 只有 execute 的一轮 LLM 调用：没有 plan/reflect 的额外两次
    assert len(llm.calls) == 1
    assert not any(p.get("phase") in ("plan", "reflect") for _, p in events)


def test_agent_loop_react_only_history_and_runtime_overrides() -> None:
    """history 拼在 system 与当前问题之间；max_tool_rounds 覆盖生效；model/context 透传。"""
    context_marker = object()
    executed: list[tuple[str, dict]] = []

    def _tool_executor(name: str, args: dict) -> str:
        executed.append((name, args))
        return "晴，20 度"

    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')], usage=_Usage(1, 1)),
        _Resp(content="北京晴。", usage=_Usage(2, 2)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    config = {
        "modleName": "m1",
        "systemPrompt": "S",
        "maxToolRounds": 1,
        "tools": [{"name": "get_weather", "description": "天气", "parameters": {"type": "object", "properties": {}}}],
    }
    runtime_input = {
        "react_only": True,
        "input": "天气怎么样",
        "history": [
            {"role": "user", "content": "早"},
            {"role": "assistant", "content": "你好"},
            {"role": "system", "content": "非法角色应被过滤"},
            {"role": "user", "content": ""},
        ],
        "max_tool_rounds": 2,
        "context": context_marker,
    }

    ctx = _make_runtime_ctx(services, config, runtime_input)
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    # config maxToolRounds=1 本会在第一轮截断，运行期覆盖为 2 才能完成第二轮收敛
    assert result.outputs["output"] == "北京晴。"
    assert executed == [("get_weather", {"city": "北京"})]

    first_call = llm.calls[0]
    assert first_call["model"] == "m1"
    assert first_call["context"] is context_marker
    # system 无任务清单后缀（plan 跳过），history 过滤后原序拼接。
    # messages 为活引用（内核就地追加 assistant/tool 记录），故断言初始前缀 4 条
    assert [m["role"] for m in first_call["messages"][:4]] == ["system", "user", "assistant", "user"]
    assert "任务清单" not in first_call["messages"][0]["content"]
    assert first_call["messages"][3]["content"] == "天气怎么样"


def test_agent_loop_react_only_dict_context_restored() -> None:
    """20261106 review 修正：chat 入参以 to_storage_dict 平铺形态进画布（run 表
    JSONB 约束），节点内还原为 AgentRunContext 再透传给 LLM。"""
    tenant_id, agent_id, user_id = uuid4(), uuid4(), uuid4()
    expected = AgentRunContext(
        agent_id=agent_id, tenant_id=tenant_id, user_id=user_id,
        conversation_id="conv-1", run_id="run-fixed",
    )
    json.dumps(expected.to_storage_dict())

    llm = _ScriptedLLM([_Resp(content="完成。", usage=_Usage(1, 1))])
    services = ServiceRegistry({"llm": llm})
    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {"react_only": True, "input": "你好", "context": expected.to_storage_dict()},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    restored = llm.calls[0]["context"]
    assert isinstance(restored, AgentRunContext)
    assert (restored.agent_id, restored.tenant_id, restored.user_id) == (agent_id, tenant_id, user_id)
    assert restored.conversation_id == "conv-1" and restored.run_id == "run-fixed"


def test_agent_loop_react_only_trace_events_carry_chat_mapping_fields() -> None:
    """trace 事件 additive 补齐 chat SSE 映射所需字段（旧字段保持不变）。"""
    events: list[tuple[str, dict]] = []

    async def _emit(etype: str, payload: dict) -> None:
        events.append((etype, payload))

    def _tool_executor(name: str, args: dict) -> str:
        return "晴，20 度"

    script = [
        _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')], usage=_Usage(3, 4)),
        _Resp(content="北京 20 度。", usage=_Usage(5, 6)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "S",
         "tools": [{"name": "get_weather", "parameters": {"type": "object", "properties": {}}}]},
        {"react_only": True, "input": "北京天气"},
        emit=_emit,
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    start = next(p for t, p in events if t == "prompt_text" and p.get("phase") == "execute" and "messages" in p)
    assert start["iteration"] == 1
    assert start["tools"][0]["function"]["name"] == "get_weather"

    assistant = next(p for t, p in events if t == "prompt_text" and p.get("role") == "assistant")
    assert assistant["iteration"] == 1
    assert assistant["usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert assistant["finish_reason"] == "stop"
    assert assistant["tool_calls"][0]["id"] == "c1"
    # 旧契约字段不变：arguments 仍是原样字符串
    assert assistant["tool_calls"][0]["arguments"] == '{"city": "北京"}'

    tstart = next(p for t, p in events if t == "tool_call_start")
    assert tstart["tool_call_id"] == "c1"
    assert tstart["arguments"] == '{"city": "北京"}'
    assert tstart["arguments_parsed"] == {"city": "北京"}

    tend = next(p for t, p in events if t == "tool_call_end")
    assert tend["tool_call_id"] == "c1"
    assert tend["is_error"] is False
    assert tend["observation"] == "晴，20 度"
