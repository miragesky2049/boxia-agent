"""0074 PRD M2：agent_loop 节点 MCP 快照展开 / 工作流即工具合成 / 引用溯源 / 预算（F6/F7/F5.3/F11.1）。

内核级预算见 test_react_loop.py；本文件覆盖节点侧合成与分派。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from internal.domain.canvas.expression import EvalContext
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes import agent_loop as agent_loop_module
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
    def __init__(self, script: list[_Resp]) -> None:
        self._script = script
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, response_format=None, **kwargs) -> _Resp:
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return self._script[idx]


def _make_ctx(
    services: ServiceRegistry,
    config: dict,
    runtime_input: dict,
    emit: Any = None,
) -> NodeContext:
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


def _services(llm: _ScriptedLLM, extra: dict[str, Any] | None = None) -> ServiceRegistry:
    return ServiceRegistry({"llm": llm, **(extra or {})})


# ---------- F6：MCP 快照展开 ----------
_MCP_SERVER = {
    "serverUrl": "http://10.0.0.8:9000/mcp",
    "name": "地图服务",
    "headers": {"X-API-KEY": "k"},
    "enabledTools": [
        {"name": "geocode", "description": "地址转坐标", "inputSchema": {
            "type": "object", "properties": {"address": {"type": "string"}},
        }},
        {"name": "no_schema_tool", "description": "", "inputSchema": None},
    ],
}


@pytest.fixture()
def mcp_calls(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _fake_call(server_url: str, tool_name: str, arguments: dict, headers=None) -> str:
        calls.append({"server": server_url, "tool": tool_name, "args": arguments, "headers": headers})
        return "116.4,39.9"

    monkeypatch.setattr(agent_loop_module, "_mcp_call_tool", _fake_call)
    return calls


def test_mcp_snapshot_synthesizes_tools_and_dispatches(monkeypatch, mcp_calls) -> None:
    llm = _ScriptedLLM([
        _Resp(content="", tool_calls=[_ToolCall("c1", "geocode", '{"address": "北京市"}')], usage=_Usage(1, 1)),
        _Resp(content="坐标 116.4,39.9", usage=_Usage(2, 2)),
    ])
    config = {"modleName": "m", "systemPrompt": "S", "mcpServers": [_MCP_SERVER]}
    ctx = _make_ctx(_services(llm), config, {"react_only": True, "input": "北京经纬度"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "坐标 116.4,39.9"
    names = [spec.name for spec in (llm.calls[0]["tools"] or [])]
    assert names == ["geocode", "no_schema_tool"]
    assert "地址转坐标" in llm.calls[0]["tools"][0].description
    assert mcp_calls == [{
        "server": "http://10.0.0.8:9000/mcp",
        "tool": "geocode",
        "args": {"address": "北京市"},
        "headers": {"X-API-KEY": "k"},
    }]


def test_mcp_reserved_or_duplicate_names_skipped(monkeypatch, mcp_calls) -> None:
    """与用户工具重名、或占用保留前缀的 MCP 项：跳过合成（配置保留），不影响其余项。"""
    server = dict(_MCP_SERVER)
    server["enabledTools"] = [
        {"name": "my_tool", "description": "用户已声明", "inputSchema": {}},
        {"name": "workflow_1", "description": "占用保留前缀", "inputSchema": {}},
        {"name": "knowledge_search_1", "description": "占用保留前缀", "inputSchema": {}},
        {"name": "kept", "description": "保留", "inputSchema": {}},
    ]
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tools": [{"name": "my_tool", "description": "d", "parameters": {"type": "object"}}],
        "mcpServers": [server],
    }
    ctx = _make_ctx(_services(llm), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    names = [spec.name for spec in (llm.calls[0]["tools"] or [])]
    assert names == ["my_tool", "kept"]
    assert mcp_calls == []


# ---------- F7：工作流即工具 ----------
class _FakeWorkflowTool:
    def __init__(self, described: dict | None = None, error: bool = False) -> None:
        self._described = described
        self._error = error
        self.describe_chains: list[list[str]] = []
        self.invoke_calls: list[dict] = []

    async def describe(self, application_id: str, chain: list[str]) -> dict | None:
        self.describe_chains.append(list(chain))
        if self._error:
            raise RuntimeError("数据库不可用")
        return self._described

    async def invoke(self, application_id: str, arguments: dict, chain: list[str]) -> str:
        self.invoke_calls.append({"app": application_id, "args": arguments, "chain": list(chain)})
        return "工作流输出：已退款"


_WF_DESCRIBED = {
    "name": "退款流程",
    "description": "按订单号执行退款",
    "parameters": {
        "type": "object",
        "properties": {"order_no": {"type": "string", "description": "订单号"}},
        "required": ["order_no"],
    },
}


def test_workflow_mount_synthesizes_named_tool_and_invokes() -> None:
    fake = _FakeWorkflowTool(_WF_DESCRIBED)
    llm = _ScriptedLLM([
        _Resp(content="", tool_calls=[_ToolCall("c1", "workflow_1", '{"order_no": "A1"}')], usage=_Usage(1, 1)),
        _Resp(content="退款完成", usage=_Usage(2, 2)),
    ])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "workflows": [{"applicationId": "4f1d2c3b-0000-0000-0000-000000000001", "name": "退款流程"}],
    }
    runtime_input = {"react_only": True, "input": "给 A1 退款", "workflow_chain": ["parent-wf-id"]}
    ctx = _make_ctx(_services(llm, {"workflow_tool": fake}), config, runtime_input)
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "退款完成"
    spec = llm.calls[0]["tools"][0]
    assert spec.name == "workflow_1"
    assert "退款流程" in spec.description and "启动参数" in spec.description
    assert spec.parameters == _WF_DESCRIBED["parameters"]
    # chain 来自运行入参并原样下传（应用层端口内做环/深度判定）
    assert fake.describe_chains == [["parent-wf-id"]]
    assert fake.invoke_calls == [{
        "app": "4f1d2c3b-0000-0000-0000-000000000001",
        "args": {"order_no": "A1"},
        "chain": ["parent-wf-id"],
    }]


def test_workflow_describe_unavailable_skipped_keeps_index() -> None:
    """不可用挂载（describe 返回 None）跳过；workflow_N 序号仍与配置序一致。"""

    class _PartialFake(_FakeWorkflowTool):
        async def describe(self, application_id: str, chain: list[str]) -> dict | None:
            self.describe_chains.append(list(chain))
            return None if application_id.endswith("1") else _WF_DESCRIBED

    fake = _PartialFake(None)
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "workflows": [
            {"applicationId": "aaaaaaaa-0000-0000-0000-000000000001"},
            {"applicationId": "aaaaaaaa-0000-0000-0000-000000000002"},
        ],
    }
    ctx = _make_ctx(_services(llm, {"workflow_tool": fake}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    specs = llm.calls[0]["tools"] or []
    assert [spec.name for spec in specs] == ["workflow_2"]


def test_workflow_describe_error_skipped() -> None:
    fake = _FakeWorkflowTool(error=True)
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "workflows": [{"applicationId": "aaaaaaaa-0000-0000-0000-000000000001"}],
    }
    ctx = _make_ctx(_services(llm, {"workflow_tool": fake}), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert (llm.calls[0]["tools"] or []) == []


def test_workflow_service_absent_skips_mount() -> None:
    """workflow_tool 未注册（如缺依赖装配的旁路）：不合成、不抛错。"""
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "workflows": [{"applicationId": "aaaaaaaa-0000-0000-0000-000000000001"}],
    }
    ctx = _make_ctx(_services(llm), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert result.outputs["output"] == "done"


# ---------- F5.3：tool_call_end 携带 chunks_meta ----------
class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content
        self.metadata: dict = {}
        self.chunk_id = "c-9"
        self.dataset_id = "d1"
        self.document_id = "doc-9"


class _FakeResult:
    def __init__(self, content: str, score: float) -> None:
        self.chunk = _FakeChunk(content)
        self.score = score


class _FakeEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _FakeStore:
    async def search(self, *, dataset_id, query_vector, top_k, tenant_id) -> list[_FakeResult]:
        return [_FakeResult("退款需在7天内申请", 0.9123)]


def test_knowledge_tool_end_carries_chunks_meta() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    llm = _ScriptedLLM([
        _Resp(content="", tool_calls=[_ToolCall("c1", "knowledge_search_1", '{"query": "退款"}')], usage=_Usage(1, 1)),
        _Resp(content="已回答", usage=_Usage(2, 2)),
    ])
    services = _services(llm, {"embedding": _FakeEmbedding(), "vector_store": _FakeStore()})
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "datasets": [{"datasetId": "d1", "name": "售后手册", "mode": "onDemand", "topK": 3}],
    }
    ctx = _make_ctx(services, config, {"react_only": True, "input": "退款期限"}, emit=_emit)
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    tool_ends = [p for et, p in events if et == "tool_call_end"]
    assert len(tool_ends) == 1
    meta = tool_ends[0]["chunks_meta"]
    assert meta[0]["dataset_name"] == "售后手册"
    assert meta[0]["chunk_id"] == "c-9" and meta[0]["document_id"] == "doc-9"
    assert meta[0]["score"] == 0.9123
    assert meta[0]["excerpt"].startswith("退款需在")


# ---------- F11.1：节点侧预算透出 ----------
def test_node_token_budget_marks_finish_reason_and_skips_tool() -> None:
    touched: list[str] = []

    def executor(name: str, args: dict) -> str:
        touched.append(name)
        return "ok"

    llm = _ScriptedLLM([
        _Resp(content="", tool_calls=[_ToolCall("c1", "get_weather", "{}")], usage=_Usage(60, 50)),
    ])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tokenBudget": 100,
        "tools": [{"name": "get_weather", "description": "d", "parameters": {"type": "object"}}],
    }
    ctx = _make_ctx(_services(llm, {"tool_executor": executor}), config, {"react_only": True, "input": "q"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert touched == []
    assert result.outputs["finish_reason"] == "budget_exceeded"
    assert "预算已用尽" in result.outputs["output"]


def test_node_deep_mode_budget_after_reflect() -> None:
    """深度模式：execute 收敛 + reflect 未达标后累计超预算 → 不再跑下一轮 execute。"""
    plan = _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "g"}]}), usage=_Usage(30, 20))
    execute1 = _Resp(content="初步回答", usage=_Usage(20, 10))
    reflect1 = _Resp(content=json.dumps({"done": False, "suggestion": "继续"}), usage=_Usage(20, 20))
    reflect2 = _Resp(content=json.dumps({"done": True}), usage=_Usage(1, 1))
    llm = _ScriptedLLM([plan, execute1, reflect1, execute1, reflect2])
    config = {"modleName": "m", "systemPrompt": "S", "tokenBudget": 100}
    ctx = _make_ctx(_services(llm), config, {"input": "q"})  # react_only 缺省 False → 深度模式
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["finish_reason"] == "budget_exceeded"
    # plan(50)+execute(30)+reflect(40)=120 ≥ 100 → reflect 后停，无第二次 execute 调用
    assert len(llm.calls) == 3
    assert result.outputs["output"] == "初步回答"
