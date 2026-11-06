"""20261106 P3：chat 入口画布通道（trace 事件 -> chat SSE 兼容契约映射）单测。

覆盖：
1. 满足画布条件（agent_loop 节点 + 显式 tools/modleName/systemPrompt）时，
   run_agent_stream 走 runner_factory，trace 事件被映射为与进程内通道逐字段
   一致的帧序列，并完成 user/assistant 落库（run 绑定）。
2. 不满足条件时回退进程内通道/打字机通道，runner_factory 不被触达（行为等价旧通道）。
3. 画布运行异常统一转 error 帧且不落 assistant 消息。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from internal.application.apps.chat_service import ChatService
from internal.domain.agent.run_context import AgentRunContext


class _Uow:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Principal:
    def __init__(self, tenant_id, user_id) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.username = "tester"


class _AppService:
    def __init__(self, graph: dict) -> None:
        self._graph = graph

    def assert_user_can_view(self, application_id, tenant_id, user_id) -> dict:
        return {"name": "天气助手", "description": "", "flow_type": "agent"}

    async def get_runtime_graph(self, application_id, tenant_id) -> dict:
        return self._graph


class _ConvRepo:
    def __init__(self, cid, principal, application_id) -> None:
        self._conv = {"id": cid, "user_id": principal.user_id,
                      "application_id": application_id, "tenant_id": principal.tenant_id}

    def get_conversation(self, conversation_id):
        return self._conv

    def touch(self, conversation_id) -> None:
        pass


class _MsgRepo:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []

    def append_message(self, **kwargs) -> int:
        self.appended.append(kwargs)
        return len(self.appended)


class _ModelService:
    def __init__(self, client) -> None:
        self._client = client
        self.calls: list[tuple[str, Any]] = []

    def get_client_for_tenant(self, model_id, tenant_id):
        self.calls.append((model_id, tenant_id))
        return self._client


class _UsageObj:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _ToolCallObj:
    def __init__(self, id_: str, name: str, arguments: str) -> None:
        self.id = id_
        self.function = _ToolFnHolder(name, arguments)


class _ToolFnHolder:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _RespObj:
    def __init__(self, content: str, tool_calls: list | None = None,
                 usage: _UsageObj | None = None, finish_reason: str = "stop") -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage or _UsageObj(1, 1)
        self.finish_reason = finish_reason
        self.reasoning_content = ""


class _FakeChatClient:
    """进程内通道用：scripted chat / chat_stream。"""

    def __init__(self, script: list[_RespObj] | None = None,
                 stream_chunks: list[Any] | None = None) -> None:
        self._script = list(script or [])
        self._chunks = list(stream_chunks or [])
        self.chat_calls: list[dict] = []

    async def chat(self, *, messages, tools=None, context=None, **kwargs):
        self.chat_calls.append({"messages": messages, "tools": tools, "context": context})
        idx = min(len(self.chat_calls) - 1, len(self._script) - 1)
        return self._script[idx]

    async def chat_stream(self, *, messages, **kwargs):
        for chunk in self._chunks:
            yield chunk


def _canvas_graph() -> dict:
    """真实持久化形态（coze 数字 type "100" + data.inputs ValueExpressionDTO），
    与 application_service._default_graph 的写入结构一致。"""

    def literal(value: object) -> dict:
        return {"value": {"type": "literal", "content": value}}

    return {
        "nodes": [{
            "id": "loop_x",
            "type": "100",
            "data": {
                "inputs": {
                    "modleName": literal("m1"),
                    "systemPrompt": literal("你是天气助手"),
                    "maxToolRounds": literal(3),
                    "tools": literal([{
                        "name": "get_weather",
                        "description": "天气",
                        "parameters": {"type": "object", "properties": {}},
                    }]),
                },
                "outputs": [],
            },
        }],
        "edges": [],
    }


def _canvas_trace_events() -> list[tuple[str, dict]]:
    """与 AgentLoopNodeHandler._execute 实际外抛的 trace 形态一致（含 P3 additive 字段）。"""
    return [
        ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
        ("prompt_text", {
            "phase": "execute", "reflect_round": 0, "tool_round": 0,
            "iteration": 1,
            "tools": [{"type": "function", "function": {"name": "get_weather", "description": "天气", "parameters": {}}}],
            "messages": [{"role": "system", "content": "你是天气助手"}, {"role": "user", "content": "北京天气"}],
        }),
        ("prompt_text", {
            "phase": "execute", "reflect_round": 0, "tool_round": 0,
            "iteration": 1, "role": "assistant", "content": "",
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            "finish_reason": "tool_calls",
            "tool_calls": [{"id": "c1", "name": "get_weather", "arguments": '{"city": "北京"}'}],
        }),
        ("tool_call_start", {
            "name": "get_weather", "arguments": '{"city": "北京"}',
            "tool_call_id": "c1", "arguments_parsed": {"city": "北京"},
            "reflect_round": 0, "tool_round": 0,
        }),
        ("tool_call_end", {
            "name": "get_weather", "arguments": '{"city": "北京"}',
            "tool_call_id": "c1", "is_error": False,
            "reflect_round": 0, "tool_round": 0, "observation": "晴，20 度",
        }),
        ("prompt_text", {
            "phase": "execute", "reflect_round": 0, "tool_round": 1,
            "iteration": 2,
            "tools": [], "messages": [],
        }),
        ("prompt_text", {
            "phase": "execute", "reflect_round": 0, "tool_round": 1,
            "iteration": 2, "role": "assistant", "content": "北京 20 度。",
            "usage": {"prompt_tokens": 6, "completion_tokens": 6, "total_tokens": 12},
            "finish_reason": "stop",
            "tool_calls": [],
        }),
        ("node_end", {
            "node_id": "loop_x", "status": "success",
            "outputs": {
                "output": "北京 20 度。", "plan": [], "reflect_history": [], "model": "m1",
                "usage": {"prompt_tokens": 9, "completion_tokens": 10, "total_tokens": 19},
            },
            "duration_ms": 12,
        }),
    ]


class _FakeRunner:
    def __init__(self, run_id, on_node_event, events, error: Exception | None = None) -> None:
        self.run_id = run_id
        self.thread_id = "t"
        self.application_id = uuid4()
        self._events = events
        self._error = error
        self._emit = on_node_event
        self.ensure_inputs: dict[str, Any] | None = None
        self.invoke_inputs: dict[str, Any] | None = None

    def ensure_run(self, input_data: dict[str, Any]) -> None:
        self.ensure_inputs = input_data

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.invoke_inputs = input_data
        for event_type, payload in self._events:
            await self._emit(event_type, payload)
        if self._error is not None:
            raise self._error
        return {"output": "北京 20 度。"}


def _make_service(
    graph: dict,
    *,
    runner_events: list[tuple[str, dict]] | None = None,
    runner_error: Exception | None = None,
    client: _FakeChatClient | None = None,
    tool_executor=None,
) -> tuple[ChatService, dict[str, Any]]:
    tenant_id, user_id = uuid4(), uuid4()
    cid = uuid4()
    app_id = uuid4()
    principal = _Principal(tenant_id, user_id)
    uow = _Uow()
    app_service = _AppService(graph)
    conv_repo = _ConvRepo(cid, principal, app_id)
    msg_repo = _MsgRepo()
    model_service = _ModelService(client or _FakeChatClient())
    captured: dict[str, Any] = {"factory_kwargs": [], "runner": None}

    async def runner_factory(_app, _uow, _ctx, **kwargs):
        captured["factory_kwargs"].append(kwargs)
        runner = _FakeRunner(
            run_id=kwargs.get("run_id"),
            on_node_event=kwargs.get("on_node_event"),
            events=runner_events if runner_events is not None else _canvas_trace_events(),
            error=runner_error,
        )
        captured["runner"] = runner
        return runner

    def tool_executor_factory(application_id, run_id):
        return tool_executor or (lambda name, args: "晴，20 度")

    service = ChatService(
        uow,
        object(),
        principal,
        runner_factory,
        app_service=app_service,
        model_service=model_service,
        resource_service=object(),
        conv_repo=conv_repo,
        msg_repo=msg_repo,
        run_repo=object(),
        default_llm_model_id="default-m",
        tool_executor_factory=tool_executor_factory,
    )
    captured.update(uow=uow, msg_repo=msg_repo, model_service=model_service, cid=cid,
                    application_id=app_id, tenant_id=tenant_id, user_id=user_id)
    return service, captured


async def _collect(service: ChatService, application_id, query: str, cid, history=None):
    frames: list[tuple[str, dict]] = []
    async for name, payload in service.run_agent_stream(application_id, query, cid, history):
        frames.append((name, payload))
    return frames


def test_chat_canvas_maps_trace_to_sse_contract_and_persists() -> None:
    service, cap = _make_service(_canvas_graph())
    app_id, cid = cap["application_id"], cap["cid"]

    frames = asyncio.run(_collect(service, app_id, "北京天气", cid,
                                  history=[{"role": "user", "content": "早"}]))
    names = [name for name, _ in frames]
    assert names == [
        "run_start", "llm_start", "llm_end", "tool_start", "tool_end",
        "llm_start", "llm_end", "result", "final",
    ]

    run_start = frames[0][1]
    assert run_start["tools"] == ["get_weather"]

    # 帧 payload 与进程内通道逐字段对齐
    llm_end1 = frames[2][1]
    assert llm_end1["iteration"] == 1 and llm_end1["usage"]["total_tokens"] == 7
    assert llm_end1["tool_calls"] == [{"id": "c1", "name": "get_weather", "arguments": '{"city": "北京"}'}]
    tool_start = frames[3][1]
    assert tool_start == {"tool_call_id": "c1", "name": "get_weather", "arguments": {"city": "北京"}}
    tool_end = frames[4][1]
    assert tool_end == {"tool_call_id": "c1", "name": "get_weather", "observation": "晴，20 度", "is_error": False}
    result = frames[7][1]
    assert result["content"] == "北京 20 度。"
    assert result["iterations"] == 2
    assert result["finish_reason"] == "stop"
    assert result["usage"] == {"prompt_tokens": 9, "completion_tokens": 10, "total_tokens": 19}
    assert result["tool_traces"] == [
        {"tool_call_id": "c1", "name": "get_weather", "observation": "晴，20 度", "is_error": False},
    ]

    # 运行入参走 react_only 通道，run_id 与 run_start 帧一致
    runner = cap["runner"]
    assert runner.invoke_inputs["react_only"] is True
    assert runner.invoke_inputs["max_tool_rounds"] == 3
    assert runner.invoke_inputs["input"] == "北京天气"
    assert runner.invoke_inputs["history"] == [{"role": "user", "content": "早"}]
    # 20261106 review 修正回归防护：start_inputs 要进 run 表 JSONB（裸 json.dumps），
    # context 必须是平铺字典而非 AgentRunContext 对象，否则 insert_run 必抛
    context_input = runner.invoke_inputs["context"]
    assert isinstance(context_input, dict)
    json.dumps(runner.invoke_inputs, ensure_ascii=False)
    assert context_input["agent_id"] == str(app_id)
    assert context_input["tenant_id"] == str(cap["tenant_id"])
    assert context_input["run_id"] == run_start["run_id"]
    assert str(runner.run_id) == run_start["run_id"]

    factory_kwargs = cap["factory_kwargs"][0]
    assert factory_kwargs["thread_id"] == str(cid)
    assert factory_kwargs["conversation_id"] == cid
    assert callable(factory_kwargs["on_node_event"])

    # 落库：user 绑定 run，assistant 绑定 run + usage/iterations 元数据
    user_msg, assistant_msg = cap["msg_repo"].appended[0], cap["msg_repo"].appended[1]
    assert user_msg["role"] == "user" and user_msg["run_id"] == runner.run_id
    assert assistant_msg["role"] == "assistant" and assistant_msg["run_id"] == runner.run_id
    assert assistant_msg["content"] == "北京 20 度。"
    assert assistant_msg["metadata"] == {
        "usage": {"prompt_tokens": 9, "completion_tokens": 10, "total_tokens": 19},
        "iterations": 2,
    }
    # 收敛轮 tool_calls 为空 -> 落库 None（与进程内通道一致）
    assert assistant_msg["tool_calls"] is None
    assert cap["uow"].commits == 1
    # 画布通道不构造应用侧 LLM client（模型解析在 runtime 内完成）
    assert cap["model_service"].calls == []


def test_chat_falls_back_to_inprocess_kernel_when_system_prompt_missing() -> None:
    """systemPrompt 缺失时画布节点会回退默认 system，与旧通道不等价——必须留在进程内通道。"""
    graph = _canvas_graph()
    del graph["nodes"][0]["data"]["inputs"]["systemPrompt"]
    client = _FakeChatClient(script=[
        _RespObj(content="", tool_calls=[_ToolCallObj("c1", "get_weather", '{"city": "北京"}')],
                 usage=_UsageObj(3, 4), finish_reason="tool_calls"),
        _RespObj(content="北京 20 度。", usage=_UsageObj(6, 6)),
    ])
    service, cap = _make_service(graph, client=client)
    app_id, cid = cap["application_id"], cap["cid"]

    frames = asyncio.run(_collect(service, app_id, "北京天气", cid))
    names = [name for name, _ in frames]
    assert names == [
        "run_start", "llm_start", "llm_end", "tool_start", "tool_end",
        "llm_start", "llm_end", "result", "final",
    ]
    # 进程内通道：runner_factory 未被触达，且消息落库 run_id 为空
    assert cap["factory_kwargs"] == []
    assert cap["msg_repo"].appended[0].get("run_id") is None
    assert cap["msg_repo"].appended[1].get("run_id") is None
    # LLM 请求带 AgentRunContext（租户 header 链路）
    assert isinstance(client.chat_calls[0]["context"], AgentRunContext)


def test_chat_falls_back_to_typewriter_without_tools() -> None:
    """无 tools 时仍走打字机通道：llm_token 逐块、runner 不构造（行为与改造前一致）。"""
    graph = _canvas_graph()
    del graph["nodes"][0]["data"]["inputs"]["tools"]

    class _Chunk:
        def __init__(self, content: str, usage: _UsageObj | None = None, reason: str = "") -> None:
            self.content = content
            self.usage = usage or _UsageObj(0, 0)
            self.finish_reason = reason

    client = _FakeChatClient(stream_chunks=[
        _Chunk("北京", reason=""), _Chunk(" 20 度。", usage=_UsageObj(5, 6), reason="stop"),
    ])
    service, cap = _make_service(graph, client=client)
    frames = asyncio.run(_collect(service, cap["application_id"], "北京天气", cap["cid"]))
    names = [name for name, _ in frames]
    assert names == ["run_start", "llm_start", "llm_token", "llm_token", "llm_end", "result", "final"]
    assert frames[2][1] == {"delta": "北京"}
    result = frames[5][1]
    assert result["content"] == "北京 20 度。"
    assert result["iterations"] == 1
    assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}
    assert cap["factory_kwargs"] == []


def test_chat_canvas_error_yields_error_frame_without_assistant_persist() -> None:
    service, cap = _make_service(_canvas_graph(), runner_events=[],
                                 runner_error=RuntimeError("模型服务不可用"))
    frames = asyncio.run(_collect(service, cap["application_id"], "北京天气", cap["cid"]))
    names = [name for name, _ in frames]
    assert names == ["run_start", "error", "final"]
    assert frames[1][1] == {"message": "模型服务不可用", "code": "chat_failed"}
    # 仅 user 消息落库（画布通道绑定 run），assistant 不落、不提交
    assert [m["role"] for m in cap["msg_repo"].appended] == ["user"]
    assert cap["uow"].commits == 0


def test_chat_canvas_guard_when_agent_loop_not_executed() -> None:
    """invoke 正常结束但图里没跑到 agent_loop（缺连线）：守卫报 error 帧，不落空回答。"""
    service, cap = _make_service(
        _canvas_graph(),
        runner_events=[("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}})],
    )
    frames = asyncio.run(_collect(service, cap["application_id"], "北京天气", cap["cid"]))
    names = [name for name, _ in frames]
    assert names == ["run_start", "error", "final"]
    assert "agent_loop" in frames[1][1]["message"]
    assert [m["role"] for m in cap["msg_repo"].appended] == ["user"]
    assert cap["uow"].commits == 0
