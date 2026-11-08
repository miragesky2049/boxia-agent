"""M4-b T-b2/T-b5/T-b6：agent_loop MCP 会话接线（F17.2~F17.6）。

用进程内 fastmcp server（conftest `in_process_mcp_server`）断言：
握手计数=去重指纹数、审批挂起出口必关连接、SSRF 执行路径复检、isError 语义；
P1 追加：会话池档位（scope=conversation）、治理拒绝（熔断/限流）与观测记账。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from internal.domain.agent.mcp_observer import (
    MCP_STATUS_OK,
    MCP_STATUS_REJECTED,
    MCP_STATUS_TOOL_ERROR,
    MCP_STATUS_TRANSPORT_ERROR,
    configure_mcp_observer,
    mcp_observer,
)
from internal.domain.agent.mcp_session_pool import McpSessionPool
from internal.domain.canvas.expression import EvalContext
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes import agent_loop as agent_loop_module
from internal.domain.graph.nodes.agent_loop import AgentLoopNodeHandler


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
    def __init__(self, content: str, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.usage = _Usage()


class _ScriptedLLM:
    def __init__(self, script: list[_Resp]) -> None:
        self._script = script
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, **kwargs) -> _Resp:
        self.calls.append({"messages": messages, "tools": tools})
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return self._script[idx]


def _make_ctx(
    services: ServiceRegistry, config: dict, runtime_input: dict, conversation_id: Any = None
) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test",
        application_id=uuid4(),
        conversation_id=conversation_id,
    )
    return NodeContext(
        node_id="agent_1",
        node_type=NodeType.AGENT_LOOP.value,
        inputs={},
        config=config,
        env=env,
        services=services,
        eval_context=EvalContext(input=runtime_input, node_outputs={}, globals={}, env={}),
        emit_event=None,
    )


def _server(url: str, tool_names: list[str], headers: dict[str, str] | None = None) -> dict:
    schemas = {
        "echo": {"type": "object", "properties": {"text": {"type": "string"}}},
        "add": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        },
        "fail": {"type": "object", "properties": {}},
    }
    return {
        "serverUrl": url,
        "name": "s",
        "headers": headers,
        "enabledTools": [
            {"name": n, "description": n, "inputSchema": schemas.get(n, {})} for n in tool_names
        ],
    }


@pytest.fixture()
def allow_loopback(monkeypatch) -> None:
    """放行 loopback：in-process server 在 127.0.0.1，真实 SSRF 守卫会拦截，
    本组用例只验握手/复用/关闭语义，SSRF 行为另用例覆盖。"""
    monkeypatch.setattr(agent_loop_module, "validate_outbound_url", lambda url: url)


def test_run_level_handshake_dedup_across_servers(in_process_mcp_server, allow_loopback) -> None:
    """同 (url, headers) 的两条 server 配置共享指纹：多工具多轮调用只握手一次。"""
    in_process_mcp_server.reset()
    url = in_process_mcp_server.url
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[
                    _ToolCall("c1", "echo", '{"text": "a"}'),
                    _ToolCall("c2", "add", '{"a": 1, "b": 2}'),
                ],
            ),
            _Resp(content="", tool_calls=[_ToolCall("c3", "echo", '{"text": "b"}')]),
            _Resp(content="done"),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(url, ["echo"], {"X-K": "1"}), _server(url, ["add"], {"X-K": "1"})],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "done"
    assert in_process_mcp_server.handshakes == 1
    assert in_process_mcp_server.call_count == 3


def test_distinct_fingerprint_creates_distinct_sessions(
    in_process_mcp_server, allow_loopback
) -> None:
    """headers 不同即不同指纹：各自一次握手（F17.2 去重键含 headers）。"""
    in_process_mcp_server.reset()
    url = in_process_mcp_server.url
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[
                    _ToolCall("c1", "echo", '{"text": "a"}'),
                    _ToolCall("c2", "add", '{"a": 1, "b": 2}'),
                ],
            ),
            _Resp(content="done"),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(url, ["echo"], {"X-K": "1"}), _server(url, ["add"], {"X-K": "2"})],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert in_process_mcp_server.handshakes == 2


def test_ssrf_rechecked_on_execution(in_process_mcp_server) -> None:
    """执行路径 SSRF 复检（F17.3①）：loopback 地址被拦截，不发起任何连接，
    observation 以 [error] 回灌模型自纠。"""
    in_process_mcp_server.reset()
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="放弃"),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(in_process_mcp_server.url, ["echo"])],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "放弃"
    assert in_process_mcp_server.handshakes == 0
    assert in_process_mcp_server.call_count == 0
    tool_message = llm.calls[1]["messages"][-1]
    assert "[error]" in tool_message["content"]
    assert "不安全" in tool_message["content"]


def test_is_error_observation_prefixed(in_process_mcp_server, allow_loopback) -> None:
    """工具执行错误（isError）以 [error] 前缀进 observation，run 不中断（验收 5）。"""
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "fail", "{}")]),
            _Resp(content="工具失败了"),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(in_process_mcp_server.url, ["fail"])],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "工具失败了"
    tool_message = llm.calls[1]["messages"][-1]
    assert tool_message["content"].startswith("[error]")
    assert "boom-xyz" in tool_message["content"]


def test_approval_suspend_closes_sessions(
    in_process_mcp_server, allow_loopback, monkeypatch
) -> None:
    """审批挂起出口不持连：节点 return awaiting_approval 前已 close 全部会话。"""
    closed: list[Any] = []
    real_session = agent_loop_module.McpSession

    class _SpySession(real_session):  # type: ignore[misc, valid-type]
        async def close(self) -> None:
            closed.append(self.server_url)
            await super().close()

    monkeypatch.setattr(agent_loop_module, "McpSession", _SpySession)
    url = in_process_mcp_server.url
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(url, ["echo"])],
        "sensitiveTools": [{"name": "echo"}],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs.get("awaiting_approval") is True
    assert closed == [url]


def test_exception_path_closes_sessions(in_process_mcp_server, allow_loopback, monkeypatch) -> None:
    """执行中断抛（LLM 异常）同样经过 finally 全关：泄漏面为零。"""
    closed: list[Any] = []
    real_session = agent_loop_module.McpSession

    class _SpySession(real_session):  # type: ignore[misc, valid-type]
        async def close(self) -> None:
            closed.append(self.server_url)
            await super().close()

    monkeypatch.setattr(agent_loop_module, "McpSession", _SpySession)

    async def _boom(*args: Any, **kwargs: Any):
        # run_react_loop 是 async generator（节点以 event_iter 消费）。
        # 节点会兜住内核 LLM 异常（转 [execute error]），只兜不住事件结构缺陷：
        # 用无 payload 的事件触发映射层 AttributeError，模拟异常出口。
        yield object()

    monkeypatch.setattr(agent_loop_module, "run_react_loop", _boom)

    class _AnyLLM:
        async def chat(self, **kwargs):  # noqa: ANN003 - 测试桩
            raise AssertionError("不应走到 llm.chat")

    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(in_process_mcp_server.url, ["echo"])],
    }
    ctx = _make_ctx(ServiceRegistry({"llm": _AnyLLM()}), config, {"react_only": True, "input": "q"})
    with pytest.raises(AttributeError):
        asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert closed == [in_process_mcp_server.url]


class _RecordingObserver:
    """MCP 观测端口测试替身：记录握手/复用/调用汇总/池水位。"""

    def __init__(self) -> None:
        self.handshakes: list[str] = []
        self.reuses: list[str] = []
        self.calls: list[Any] = []
        self.pool_sizes: list[int] = []

    def on_handshake(self, server: str) -> None:
        self.handshakes.append(server)

    def on_reuse(self, server: str) -> None:
        self.reuses.append(server)

    def observe_call(self, record: Any) -> None:
        self.calls.append(record)

    def set_pool_size(self, size: int) -> None:
        self.pool_sizes.append(size)


@pytest.fixture()
def recording_observer():
    previous = mcp_observer()
    obs = _RecordingObserver()
    configure_mcp_observer(obs)
    yield obs
    configure_mcp_observer(previous)


class _FakeBreaker:
    def __init__(self, allow_result: bool = True) -> None:
        self.allow_result = allow_result
        self.keys_checked: list[str] = []
        self.failures: list[str] = []
        self.successes: list[str] = []

    async def allow(self, key: str) -> bool:
        self.keys_checked.append(key)
        return self.allow_result

    async def record_success(self, key: str) -> None:
        self.successes.append(key)

    async def record_failure(self, key: str) -> None:
        self.failures.append(key)


class _FakeLimiter:
    def __init__(self, allow_result: bool = True) -> None:
        self.allow_result = allow_result
        self.keys_checked: list[str] = []

    async def allow(self, key: str) -> bool:
        self.keys_checked.append(key)
        return self.allow_result


def _single_call_config(url: str, tools: list[str], **extra: Any) -> dict:
    config: dict[str, Any] = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [_server(url, tools)],
    }
    config.update(extra)
    return config


def test_conversation_scope_pool_reuses_across_runs(
    in_process_mcp_server, allow_loopback, monkeypatch, recording_observer
) -> None:
    """F17.4：scope=conversation 走会话池，两次 run 同会话仅 1 次握手且出口不关连接。"""
    in_process_mcp_server.reset()
    pool = McpSessionPool()
    monkeypatch.setattr(agent_loop_module, "get_mcp_session_pool", lambda: pool)
    url = in_process_mcp_server.url
    conv = uuid4()
    config = _single_call_config(url, ["echo"], mcpSession={"scope": "conversation"})

    async def _two_runs() -> None:
        for text in ("a", "b"):
            llm = _ScriptedLLM(
                [
                    _Resp(
                        content="", tool_calls=[_ToolCall("c1", "echo", f'{{"text": "{text}"}}')]
                    ),
                    _Resp(content="done"),
                ]
            )
            ctx = _make_ctx(
                ServiceRegistry({"llm": llm}),
                config,
                {"react_only": True, "input": "q"},
                conversation_id=conv,
            )
            await AgentLoopNodeHandler().run(ctx)

    asyncio.run(_two_runs())
    assert in_process_mcp_server.handshakes == 1
    assert in_process_mcp_server.call_count == 2
    assert pool.size == 1
    assert recording_observer.reuses == [url]


def test_conversation_scope_without_cid_falls_back_to_run(
    in_process_mcp_server, allow_loopback, monkeypatch
) -> None:
    """R13 前提缺失（无 conversation_id）：不得触碰会话池，回落 run 档且出口全关。"""
    closed: list[Any] = []
    real_session = agent_loop_module.McpSession

    class _SpySession(real_session):  # type: ignore[misc, valid-type]
        async def close(self) -> None:
            closed.append(self.server_url)
            await super().close()

    monkeypatch.setattr(agent_loop_module, "McpSession", _SpySession)

    def _boom_pool() -> McpSessionPool:
        raise AssertionError("缺 conversation_id 时不应使用会话池")

    monkeypatch.setattr(agent_loop_module, "get_mcp_session_pool", _boom_pool)
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="done"),
        ]
    )
    config = _single_call_config(
        in_process_mcp_server.url, ["echo"], mcpSession={"scope": "conversation"}
    )
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert closed == [in_process_mcp_server.url]


def test_conversation_scope_passes_timeout_and_context_to_pool(
    in_process_mcp_server, monkeypatch
) -> None:
    """池档透传条目级 timeoutSeconds / conversation_id / headers（F17.3② × F17.4）。"""
    recorded: list[tuple] = []

    class _RecordingPool:
        async def call(
            self, conversation_id, server_url, headers, timeout_seconds, tool_name, arguments
        ) -> str:
            recorded.append((conversation_id, server_url, headers, timeout_seconds, tool_name))
            return "ok"

    def _boom_session(*args: Any, **kwargs: Any):
        raise AssertionError("池档下不应构造 run 级 McpSession")

    monkeypatch.setattr(agent_loop_module, "get_mcp_session_pool", lambda: _RecordingPool())
    monkeypatch.setattr(agent_loop_module, "McpSession", _boom_session)
    monkeypatch.setattr(agent_loop_module, "validate_outbound_url", lambda url: url)
    server = _server(in_process_mcp_server.url, ["echo"], {"X-K": "1"})
    server["timeoutSeconds"] = 45
    conv = uuid4()
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="done"),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "mcpServers": [server],
        "mcpSession": {"scope": "conversation"},
    }
    ctx = _make_ctx(
        ServiceRegistry({"llm": llm}),
        config,
        {"react_only": True, "input": "q"},
        conversation_id=conv,
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "done"
    assert recorded == [(str(conv), in_process_mcp_server.url, {"X-K": "1"}, 45.0, "echo")]


def test_breaker_open_rejects_before_connect(
    in_process_mcp_server, allow_loopback, monkeypatch, recording_observer
) -> None:
    """F17.5：熔断打开时执行前即拒（不发起连接、不耗限流额度），observation 提示稍后重试。"""
    in_process_mcp_server.reset()
    breaker, limiter = _FakeBreaker(allow_result=False), _FakeLimiter()
    monkeypatch.setattr(agent_loop_module, "get_mcp_breaker", lambda: breaker)
    monkeypatch.setattr(agent_loop_module, "get_mcp_limiter", lambda: limiter)
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="放弃"),
        ]
    )
    config = _single_call_config(in_process_mcp_server.url, ["echo"])
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "放弃"
    assert in_process_mcp_server.handshakes == 0
    tool_message = llm.calls[1]["messages"][-1]
    assert "[error]" in tool_message["content"] and "熔断" in tool_message["content"]
    assert breaker.keys_checked and breaker.keys_checked[0].endswith(
        f":mcp:{in_process_mcp_server.url}"
    )
    assert breaker.failures == [] and breaker.successes == []
    assert limiter.keys_checked == []
    assert [r.status for r in recording_observer.calls] == [MCP_STATUS_REJECTED]


def test_rate_limited_rejects(
    in_process_mcp_server, allow_loopback, monkeypatch, recording_observer
) -> None:
    """F17.5：限流拒绝走 rejected 观测口径，同样不发起连接。"""
    in_process_mcp_server.reset()
    breaker, limiter = _FakeBreaker(), _FakeLimiter(allow_result=False)
    monkeypatch.setattr(agent_loop_module, "get_mcp_breaker", lambda: breaker)
    monkeypatch.setattr(agent_loop_module, "get_mcp_limiter", lambda: limiter)
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="放弃"),
        ]
    )
    config = _single_call_config(in_process_mcp_server.url, ["echo"])
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    tool_message = llm.calls[1]["messages"][-1]
    assert "[error]" in tool_message["content"] and "限流" in tool_message["content"]
    assert in_process_mcp_server.handshakes == 0
    assert limiter.keys_checked == [breaker.keys_checked[0].split(":")[0]]
    assert [r.status for r in recording_observer.calls] == [MCP_STATUS_REJECTED]


def test_transport_failure_records_breaker_failure(
    in_process_mcp_server, allow_loopback, monkeypatch, recording_observer
) -> None:
    """连接失败计入熔断失败簿并上报 transport_error 观测（F17.5/F17.6）。"""
    breaker = _FakeBreaker()
    monkeypatch.setattr(agent_loop_module, "get_mcp_breaker", lambda: breaker)
    monkeypatch.setattr(agent_loop_module, "get_mcp_limiter", lambda: _FakeLimiter())
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "echo", '{"text": "a"}')]),
            _Resp(content="放弃"),
        ]
    )
    # 端口 1 必然拒连：覆盖 McpClientError 传播路径（不依赖 in-process server）
    config = _single_call_config("http://127.0.0.1:1/mcp", ["echo"])
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert breaker.failures == breaker.keys_checked
    assert breaker.successes == []
    assert [r.status for r in recording_observer.calls] == [MCP_STATUS_TRANSPORT_ERROR]


def test_observer_records_ok_and_tool_error_status(
    in_process_mcp_server, allow_loopback, recording_observer
) -> None:
    """F17.6：正常返回 ok、isError 返回 tool_error 两种口径分开记账。"""
    in_process_mcp_server.reset()
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[
                    _ToolCall("c1", "echo", '{"text": "a"}'),
                    _ToolCall("c2", "fail", "{}"),
                ],
            ),
            _Resp(content="done"),
        ]
    )
    config = _single_call_config(in_process_mcp_server.url, ["echo", "fail"])
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    records = recording_observer.calls
    assert [(r.tool, r.status) for r in records] == [
        ("echo", MCP_STATUS_OK),
        ("fail", MCP_STATUS_TOOL_ERROR),
    ]
    assert all(r.duration_seconds >= 0 for r in records)
    assert all(r.tenant and r.server == in_process_mcp_server.url for r in records)


def test_timeout_seconds_passthrough(in_process_mcp_server, monkeypatch) -> None:
    """条目级 timeoutSeconds 透传到 McpSession（F17.3②）；非法值回落 30。"""
    constructed: list[float] = []

    class _RecordingSession:
        def __init__(self, server_url: str, headers=None, timeout_seconds: float = 30.0) -> None:
            constructed.append(timeout_seconds)

        async def call_tool(self, tool_name: str, arguments: dict) -> str:
            return "ok"

        async def close(self) -> None:
            pass

    monkeypatch.setattr(agent_loop_module, "McpSession", _RecordingSession)
    monkeypatch.setattr(agent_loop_module, "validate_outbound_url", lambda url: url)
    server_a = _server(in_process_mcp_server.url, ["echo"], {"X-K": "1"})
    server_a["timeoutSeconds"] = 5
    server_b = _server(in_process_mcp_server.url, ["add"], {"X-K": "2"})
    server_b["timeoutSeconds"] = "abc"  # 非法 → 默认 30
    llm = _ScriptedLLM([_Resp(content="done")])
    config = {"modleName": "m", "systemPrompt": "S", "mcpServers": [server_a, server_b]}
    ctx = _make_ctx(ServiceRegistry({"llm": llm}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert constructed == [5.0, 30.0]
