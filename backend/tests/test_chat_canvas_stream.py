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
import contextlib
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
    def __init__(self, graph: dict, flow_type: str = "agent") -> None:
        self._graph = graph
        self._flow_type = flow_type

    def assert_user_can_view(self, application_id, tenant_id, user_id) -> dict:
        return {"name": "天气助手", "description": "", "flow_type": self._flow_type}

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
        # 0074 F8 服务端记忆：list_messages_by_conversation 的固定返回（时间正序）
        self.history_rows: list[dict[str, Any]] = []
        self.list_calls: list[int] = []

    def append_message(self, **kwargs) -> int:
        self.appended.append(kwargs)
        return len(self.appended)

    def list_messages_by_conversation(self, conversation_id, *, limit: int = 50):
        self.list_calls.append(limit)
        # 与真实仓储一致：取最近 limit 条后按时间正序返回
        return self.history_rows[-limit:]


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
    def __init__(
        self,
        run_id,
        on_node_event,
        events,
        error: Exception | None = None,
        hang: bool = False,
    ) -> None:
        self.run_id = run_id
        self.thread_id = "t"
        self.application_id = uuid4()
        self._events = events
        self._error = error
        self._hang = hang
        self._emit = on_node_event
        self.ensure_inputs: dict[str, Any] | None = None
        self.invoke_inputs: dict[str, Any] | None = None
        self.purged = 0

    def ensure_run(self, input_data: dict[str, Any]) -> None:
        self.ensure_inputs = input_data

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.invoke_inputs = input_data
        for event_type, payload in self._events:
            await self._emit(event_type, payload)
        if self._hang:
            # R6 断连用例：模拟长耗时图执行挂起，等待消费侧拆除后取消
            await asyncio.Event().wait()
        if self._error is not None:
            raise self._error
        return {"output": "北京 20 度。"}

    async def purge_thread_checkpoints(self) -> None:
        self.purged += 1


class _FakeRunRepo:
    def __init__(self) -> None:
        self.status_updates: list[dict[str, Any]] = []

    def update_run_status(self, run_id, **kwargs) -> None:
        self.status_updates.append({"run_id": run_id, **kwargs})


def _make_service(
    graph: dict,
    *,
    runner_events: list[tuple[str, dict]] | None = None,
    runner_error: Exception | None = None,
    client: _FakeChatClient | None = None,
    tool_executor=None,
    flow_type: str = "agent",
    runner_hang: bool = False,
    run_repo: Any | None = None,
) -> tuple[ChatService, dict[str, Any]]:
    tenant_id, user_id = uuid4(), uuid4()
    cid = uuid4()
    app_id = uuid4()
    principal = _Principal(tenant_id, user_id)
    uow = _Uow()
    app_service = _AppService(graph, flow_type)
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
            hang=runner_hang,
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
        run_repo=run_repo or object(),
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


# ---------- 20261107 0074 PRD F5/F8：datasets 通道条件 + 服务端记忆 ----------
def _datasets_canvas_graph(*, memory: dict | None = None) -> dict:
    """纯知识库 agent 画布：无 tools，仅 datasets（F5 校准后也应走画布通道）。"""

    def literal(value: object) -> dict:
        return {"value": {"type": "literal", "content": value}}

    inputs = {
        "modleName": literal("m1"),
        "systemPrompt": literal("你是产品顾问"),
        "datasets": literal([{"datasetId": "d1", "name": "产品库", "mode": "onDemand"}]),
    }
    if memory is not None:
        inputs["memory"] = literal(memory)
    return {"nodes": [{"id": "loop_x", "type": "100", "data": {"inputs": inputs, "outputs": []}}], "edges": []}


def test_chat_datasets_only_agent_goes_canvas_channel() -> None:
    """无 tools 仅 datasets：use_canvas 命中，runner 被触达，不再误落打字机通道。"""
    service, cap = _make_service(_datasets_canvas_graph())
    frames = asyncio.run(_collect(service, cap["application_id"], "退款政策", cap["cid"]))

    assert cap["runner"] is not None
    assert frames[0][0] == "run_start"
    assert frames[0][1]["tools"] == []
    # 打字机通道会调 chat_stream；画布通道不应触达模型客户端
    assert cap["model_service"].calls == []


def test_chat_agent_server_memory_fetched_when_history_omitted() -> None:
    """F8：前端未传 history 且 flow_type=agent → 按节点 memory 配置拉取并截断注入画布。"""
    graph = _datasets_canvas_graph(memory={"shortTerm": {"windowTurns": 1, "tokenBudget": 100000}})
    service, cap = _make_service(graph)
    cap["msg_repo"].history_rows = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]

    asyncio.run(_collect(service, cap["application_id"], "q3", cap["cid"]))

    # 拉取 limit = windowTurns * 2
    assert cap["msg_repo"].list_calls == [2]
    injected = cap["runner"].invoke_inputs["history"]
    assert injected == [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]


def test_chat_agent_explicit_empty_history_skips_server_memory() -> None:
    """显式 history=[] 表示"本轮不带历史"，不得再走服务端拉取。"""
    service, cap = _make_service(_datasets_canvas_graph())
    cap["msg_repo"].history_rows = [{"role": "user", "content": "不应出现"}]

    asyncio.run(_collect(service, cap["application_id"], "q", cap["cid"], history=[]))

    assert cap["msg_repo"].list_calls == []
    assert cap["runner"].invoke_inputs["history"] == []


def test_chat_agent_disabled_memory_returns_empty() -> None:
    """memory.enabled=false：不拉库，注入空历史。"""
    graph = _datasets_canvas_graph(memory={"shortTerm": {"enabled": False}})
    service, cap = _make_service(graph)
    cap["msg_repo"].history_rows = [{"role": "user", "content": "q1"}]

    asyncio.run(_collect(service, cap["application_id"], "q2", cap["cid"]))

    assert cap["msg_repo"].list_calls == []
    assert cap["runner"].invoke_inputs["history"] == []


def test_chatflow_never_uses_server_side_memory() -> None:
    """服务端记忆仅对 agent 型生效：chatflow 未传 history 不拉库（行为不变）。"""
    graph = _datasets_canvas_graph()
    service, cap = _make_service(graph, flow_type="chatflow")
    cap["msg_repo"].history_rows = [{"role": "user", "content": "q1"}]

    asyncio.run(_collect(service, cap["application_id"], "q2", cap["cid"]))

    assert cap["msg_repo"].list_calls == []


# ---------- 20261107 0074 PRD M2：F4 深度模式 / F5.3 溯源 / F6+F7 通道判据 / R6 断连 ----------
def _agent_graph_with(**literal_inputs: object) -> dict:
    def literal(value: object) -> dict:
        return {"value": {"type": "literal", "content": value}}

    inputs = {k: (v["value"]["content"] if isinstance(v, dict) else v) for k, v in literal_inputs.items()}
    return {
        "nodes": [{
            "id": "loop_x", "type": "100",
            "data": {
                "inputs": {key: literal(value) for key, value in inputs.items()},
                "outputs": [],
            },
        }],
        "edges": [],
    }


def test_chat_mcp_or_workflows_only_agent_goes_canvas_channel() -> None:
    """F6/F7：仅挂 MCP 快照或工作流的 agent（无 tools/datasets）也必须走画布通道。"""
    graphs = [
        _agent_graph_with(
            modleName="m1", systemPrompt="S",
            mcpServers=[{"serverUrl": "http://10.0.0.8/mcp", "enabledTools": [{"name": "geocode"}]}],
        ),
        _agent_graph_with(
            modleName="m1", systemPrompt="S",
            workflows=[{"applicationId": str(uuid4())}],
        ),
    ]
    for graph in graphs:
        service, cap = _make_service(graph, runner_events=[
            ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
            ("prompt_text", {"phase": "execute", "iteration": 1, "role": "assistant",
                             "content": "done", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                             "finish_reason": "stop", "tool_calls": []}),
            ("node_end", {"node_id": "loop_x", "status": "success", "outputs": {"output": "done"}}),
        ])
        frames = asyncio.run(_collect(service, cap["application_id"], "q", cap["cid"]))
        assert cap["runner"] is not None
        assert frames[0][0] == "run_start"
        assert cap["model_service"].calls == []


def test_chat_deep_mode_reacts_only_false_and_emits_plan_reflect_frames() -> None:
    """F4：agent+画布+planExecuteReflect → react_only=False；plan/reflect 透出 additive 帧，
    node_end 的 finish_reason 覆盖 result 帧（F11.1 预算触顶走同一通道）。"""
    graph = _canvas_graph()
    graph["nodes"][0]["data"]["inputs"]["reasoningMode"] = {
        "value": {"type": "literal", "content": "planExecuteReflect"}
    }
    events = [
        ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
        ("prompt_text", {"phase": "plan", "role": "assistant",
                         "content": '{"tasks": [{"id": "t1", "goal": "查天气"}]}'}),
        ("prompt_text", {"phase": "execute", "iteration": 1, "reflect_round": 0, "role": "assistant",
                         "content": "北京 20 度。",
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                         "finish_reason": "stop", "tool_calls": []}),
        ("prompt_text", {"phase": "reflect", "reflect_round": 0, "role": "assistant",
                         "content": '{"done": false, "critique": "缺湿度", "suggestion": "补充"}'}),
        ("node_end", {"node_id": "loop_x", "status": "success", "outputs": {
            "output": "北京 20 度。", "plan": [{"id": "t1"}],
            "finish_reason": "budget_exceeded",
        }}),
    ]
    service, cap = _make_service(graph, runner_events=events)
    frames = asyncio.run(_collect(service, cap["application_id"], "北京天气", cap["cid"]))

    assert cap["runner"].invoke_inputs["react_only"] is False
    names = [name for name, _ in frames]
    assert names == ["run_start", "plan", "llm_end", "reflect", "result", "final"]
    plan = frames[1][1]
    assert plan["tasks"] == [{"id": "t1", "goal": "查天气"}]
    reflect = frames[3][1]
    assert reflect["reflect_round"] == 0 and reflect["done"] is False and reflect["suggestion"] == "补充"
    # node_end 透出 budget_exceeded 覆盖 execute llm_end 的 stop
    assert frames[4][1]["finish_reason"] == "budget_exceeded"


def test_chat_tool_end_maps_chunks_meta_to_chunks_frame() -> None:
    """F5.3：节点 trace 的 chunks_meta 映射为 SSE tool_end 帧的 additive chunks 键。"""
    events = _canvas_trace_events()
    for index, (event_type, payload) in enumerate(events):
        if event_type == "tool_call_end":
            events[index] = (event_type, {**payload, "chunks_meta": [
                {"dataset_id": "d1", "dataset_name": "售后手册", "chunk_id": "c-1",
                 "document_id": "doc-1", "score": 0.91, "excerpt": "退款需在7天内"},
            ]})
    service, cap = _make_service(_canvas_graph(), runner_events=events)
    frames = asyncio.run(_collect(service, cap["application_id"], "北京天气", cap["cid"]))

    tool_end = next(payload for name, payload in frames if name == "tool_end")
    assert tool_end["chunks"][0]["dataset_name"] == "售后手册"
    assert tool_end["chunks"][0]["score"] == 0.91
    # 原始 4 个基础键不变（additive 只增不改）
    assert set(tool_end) == {"tool_call_id", "name", "observation", "is_error", "chunks"}


def test_chat_canvas_disconnect_marks_cancelled_and_purges_checkpoints() -> None:
    """R6：消费侧断连拆流时 run 标 cancelled（含提交）并清理 thread checkpoints。"""
    run_repo = _FakeRunRepo()
    events = [
        ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
        ("prompt_text", {"phase": "execute", "iteration": 1, "reflect_round": 0,
                         "tool_round": 0, "tools": [], "messages": []}),
        ("prompt_text", {"phase": "execute", "iteration": 1, "reflect_round": 0, "role": "assistant",
                         "content": "", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                         "finish_reason": "tool_calls",
                         "tool_calls": [{"id": "c1", "name": "get_weather", "arguments": "{}"}]}),
        ("tool_call_start", {"name": "get_weather", "arguments": "{}", "tool_call_id": "c1",
                             "arguments_parsed": {}, "reflect_round": 0, "tool_round": 0}),
    ]

    async def _go():
        app_id, cid = cap["application_id"], cap["cid"]
        agen = service.run_agent_stream(app_id, "北京天气", cid, None)
        seen: list[str] = []
        got_tool_start = asyncio.Event()

        async def consume() -> None:
            async for name, _payload in agen:
                seen.append(name)
                if name == "tool_start":
                    # 下一轮 __anext__ 将阻塞在 queue.get（runner 已挂起）——
                    # 此刻取消任务，等价 uvicorn/starlette 对断连请求的拆流方式
                    got_tool_start.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(got_tool_start.wait(), timeout=5)
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return seen

    service, cap = _make_service(
        _canvas_graph(), runner_events=events, runner_hang=True, run_repo=run_repo,
    )
    seen = asyncio.run(_go())

    assert seen == ["run_start", "llm_start", "llm_end", "tool_start", "final"]
    runner = cap["runner"]
    assert run_repo.status_updates == [{
        "run_id": runner.run_id,
        "execute_status": "cancelled",
        "error_message": "客户端断连，执行已取消",
    }]
    # 断连收口提交一次（run 行 + user 消息不随连接回滚）
    assert cap["uow"].commits == 1
    assert runner.purged == 1


# ---------- 20261107 0074 PRD F10（M3）：工具审批挂起/续跑（chat 通道编排） ----------
class _ApprovalRunRepo:
    """带挂起审批检索面的 run_repo fake：get_running_by_thread + update_run_interrupt。"""

    def __init__(self, pending_run_id, pending_payload: dict | None) -> None:
        self._pending = {
            "id": pending_run_id,
            "execute_status": "interrupted",
            "interrupt_payload": pending_payload,
        } if pending_payload is not None else None
        self.interrupt_updates: list[dict[str, Any]] = []
        self.status_updates: list[dict[str, Any]] = []
        self.queried_threads: list[str] = []

    def get_running_by_thread(self, tenant_id, application_id, thread_id):
        self.queried_threads.append(thread_id)
        return self._pending

    def update_run_interrupt(self, run_id, payload) -> None:
        self.interrupt_updates.append({"run_id": run_id, "payload": payload})

    def update_run_status(self, run_id, **kwargs) -> None:
        self.status_updates.append({"run_id": run_id, **kwargs})


def _awaiting_trace_events() -> list[tuple[str, dict]]:
    """节点整轮挂起形态的画布 trace：assistant 轮后 node_end 带 awaiting_approval。"""
    return [
        ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
        ("prompt_text", {
            "phase": "execute", "reflect_round": 0, "tool_round": 0,
            "iteration": 1, "role": "assistant", "content": "",
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            "finish_reason": "awaiting_approval",
            "tool_calls": [{"id": "c1", "name": "get_weather", "arguments": '{"city": "北京"}'}],
        }),
        ("node_end", {
            "node_id": "loop_x", "status": "success",
            "outputs": {
                "output": "", "plan": [], "model": "m1", "awaiting_approval": True,
                "approval": {
                    "type": "tool_approval", "node_id": "loop_x",
                    "iteration": 1, "tool_round": 0,
                    "pending_tool_calls": [{"id": "c1", "name": "get_weather",
                                            "arguments": '{"city": "北京"}'}],
                    "awaiting_calls": [{"id": "c1", "name": "get_weather",
                                         "arguments": '{"city": "北京"}'}],
                },
                "snapshot": {
                    "messages": [{"role": "user", "content": "北京天气"}],
                    "plan_tasks": [], "reflect_round": 0, "reflect_history": [],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                },
            },
        }),
    ]


def _approval_pending_payload() -> dict:
    return {
        "type": "tool_approval", "node_id": "loop_x", "iteration": 1, "tool_round": 0,
        "pending_tool_calls": [{"id": "c1", "name": "send_email", "arguments": "{}"}],
        "awaiting_calls": [{"id": "c1", "name": "send_email", "arguments": "{}"}],
        "snapshot": {
            "messages": [{"role": "user", "content": "发邮件"}],
            "plan_tasks": [], "reflect_round": 0, "reflect_history": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    }


def _collect_full(service, app_id, query, cid, **kwargs):
    async def _go():
        return [(n, p) async for n, p in service.run_agent_stream(app_id, query, cid, None, **kwargs)]
    return asyncio.run(_go())


def test_chat_approval_interrupt_frame_and_snapshot_persist() -> None:
    """挂起轮：interrupted 帧收尾，快照写 run payload，不落 assistant、不发 result。"""
    pending_id = uuid4()
    run_repo = _ApprovalRunRepo(pending_id, None)
    service, cap = _make_service(
        _canvas_graph(), runner_events=_awaiting_trace_events(), run_repo=run_repo,
    )
    frames = _collect_full(service, cap["application_id"], "北京天气", cap["cid"])
    names = [name for name, _ in frames]
    assert names == ["run_start", "llm_end", "interrupted", "final"]

    interrupted = frames[2][1]
    assert interrupted["approval"]["type"] == "tool_approval"
    # 帧内 approval 是展示裁剪形态，快照不外发
    assert "snapshot" not in interrupted["approval"]
    assert interrupted["run_id"] == frames[0][1]["run_id"]
    assert interrupted["conversation_id"] == str(cap["cid"])
    assert interrupted["thread_id"] == str(cap["cid"])

    # run payload = 审批展示字段 + snapshot（供后续 resume 还原执行现场）
    saved = run_repo.interrupt_updates[0]
    assert saved["payload"]["type"] == "tool_approval"
    assert saved["payload"]["snapshot"]["messages"] == [{"role": "user", "content": "北京天气"}]
    # 挂起现场提交一次；只落 user 消息
    assert cap["uow"].commits == 1
    assert [m["role"] for m in cap["msg_repo"].appended] == ["user"]


def test_chat_approval_resume_reuses_pending_run_and_snapshot() -> None:
    """续跑：复用挂起 run 行、start_inputs 携带 approval_resume、user 消息为裁决文案。"""
    pending_id = uuid4()
    run_repo = _ApprovalRunRepo(pending_id, _approval_pending_payload())
    service, cap = _make_service(_canvas_graph(), run_repo=run_repo)

    frames = _collect_full(
        service, cap["application_id"], "", cap["cid"],
        resume={"approved": True, "comment": "可以发"},
    )
    names = [name for name, _ in frames]
    assert names[-2:] == ["result", "final"]
    # run_start 帧复用被挂起的 run id
    assert frames[0][1]["run_id"] == str(pending_id)

    runner = cap["runner"]
    approval_resume = runner.invoke_inputs["approval_resume"]
    assert approval_resume["approved"] is True
    assert approval_resume["comment"] == "可以发"
    assert approval_resume["snapshot"]["messages"] == [{"role": "user", "content": "发邮件"}]
    # 快照自带执行现场：不再携带历史；线程沿用挂起 run 的会话线程
    assert runner.invoke_inputs["history"] == []
    assert cap["factory_kwargs"][0]["thread_id"] == str(cap["cid"])
    # 裁决文案作为 user 消息落库
    assert cap["msg_repo"].appended[0]["content"] == "批准执行工具调用（理由：可以发）"


def test_chat_approval_resume_without_pending_raises() -> None:
    """无可恢复挂起：ValidationError 在流开始前抛出（不落 user 消息、不构造 runner）。"""
    run_repo = _ApprovalRunRepo(uuid4(), None)
    service, cap = _make_service(_canvas_graph(), run_repo=run_repo)
    import pytest

    with pytest.raises(Exception) as exc_info:
        _collect_full(service, cap["application_id"], "", cap["cid"],
                      resume={"approved": True, "comment": ""})
    assert "没有待恢复的工具审批" in str(exc_info.value)
    assert cap["factory_kwargs"] == []
    assert cap["msg_repo"].appended == []


def test_chat_new_message_rotates_thread_when_approval_pending() -> None:
    """新消息遇未决审批：轮转子线程，旧挂起 run 的 resume 检索不被干扰。"""
    pending_id = uuid4()
    run_repo = _ApprovalRunRepo(pending_id, _approval_pending_payload())
    service, cap = _make_service(_canvas_graph(), run_repo=run_repo)

    frames = _collect_full(service, cap["application_id"], "换个话题", cap["cid"])
    assert frames[-2:][0][0] == "result"

    bound = cap["factory_kwargs"][0]["thread_id"]
    assert bound != str(cap["cid"])
    assert bound.startswith(f"{cap['cid']}:")
    # 旧挂起 run 不被本轮触碰
    assert run_repo.interrupt_updates == []
    assert run_repo.status_updates == []


def test_chat_prepare_run_and_channel_resolution() -> None:
    """统一入口预检：空消息/缺 cid/缺 approved 均 422；channel 解析回卡片。"""
    import pytest

    from internal.application.errors import ValidationError as _VE

    service, cap = _make_service(_canvas_graph())
    app_id = cap["application_id"]

    with pytest.raises(_VE):
        service.prepare_chat_run(app_id, message="  ", conversation_id=None, resume=None)
    with pytest.raises(_VE):
        service.prepare_chat_run(app_id, message="", conversation_id=None,
                                 resume={"approved": True})
    with pytest.raises(_VE):
        service.prepare_chat_run(app_id, message="", conversation_id=cap["cid"],
                                 resume={"comment": "x"})
    service.prepare_chat_run(app_id, message="hi", conversation_id=None, resume=None)
    # resolve_conversation_channel：路由分派依据（flow_type）
    assert service.resolve_conversation_channel(app_id)["flow_type"] == "agent"
