"""A6：Agent 循环节点 plan/execute/reflect 三阶段协议单测。"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.agent_loop import AgentLoopNodeHandler
from internal.domain.llm.client import LLMToolSpec


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
