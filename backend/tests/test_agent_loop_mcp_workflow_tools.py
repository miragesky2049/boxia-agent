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
    def __init__(
        self, content: str, tool_calls: list | None = None, usage: _Usage | None = None
    ) -> None:
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
    application_id: Any = None,
) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test",
        application_id=application_id or uuid4(),
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
        {
            "name": "geocode",
            "description": "地址转坐标",
            "inputSchema": {
                "type": "object",
                "properties": {"address": {"type": "string"}},
            },
        },
        {"name": "no_schema_tool", "description": "", "inputSchema": None},
    ],
}


class _McpCallLog(list):
    """调用记录 list + 关闭记录（list 不能挂属性，用子类）。"""

    def __init__(self) -> None:
        super().__init__()
        self.closes: list[str] = []


@pytest.fixture()
def mcp_calls(monkeypatch) -> _McpCallLog:
    """假 McpSession（T-b2 起执行路径走 run 级会话）：记录调用与关闭。"""
    calls = _McpCallLog()

    class _FakeMcpSession:
        def __init__(self, server_url: str, headers=None, timeout_seconds: float = 30.0) -> None:
            self._url = server_url
            self._headers = headers
            self.timeout_seconds = timeout_seconds

        async def call_tool(self, tool_name: str, arguments: dict) -> str:
            calls.append(
                {
                    "server": self._url,
                    "tool": tool_name,
                    "args": arguments,
                    "headers": self._headers,
                }
            )
            return "116.4,39.9"

        async def close(self) -> None:
            calls.closes.append(self._url)

    monkeypatch.setattr(agent_loop_module, "McpSession", _FakeMcpSession)
    return calls


def test_mcp_snapshot_synthesizes_tools_and_dispatches(monkeypatch, mcp_calls) -> None:
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "geocode", '{"address": "北京市"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="坐标 116.4,39.9", usage=_Usage(2, 2)),
        ]
    )
    config = {"modleName": "m", "systemPrompt": "S", "mcpServers": [_MCP_SERVER]}
    ctx = _make_ctx(_services(llm), config, {"react_only": True, "input": "北京经纬度"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "坐标 116.4,39.9"
    names = [spec.name for spec in (llm.calls[0]["tools"] or [])]
    assert names == ["geocode", "no_schema_tool"]
    assert "地址转坐标" in llm.calls[0]["tools"][0].description
    assert mcp_calls == [
        {
            "server": "http://10.0.0.8:9000/mcp",
            "tool": "geocode",
            "args": {"address": "北京市"},
            "headers": {"X-API-KEY": "k"},
        }
    ]
    # T-b2：节点正常出口必须 close run 级会话（同指纹仅一个 session）
    assert mcp_calls.closes == ["http://10.0.0.8:9000/mcp"]


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
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "workflow_1", '{"order_no": "A1"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="退款完成", usage=_Usage(2, 2)),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "workflows": [
            {"applicationId": "4f1d2c3b-0000-0000-0000-000000000001", "name": "退款流程"}
        ],
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
    assert fake.invoke_calls == [
        {
            "app": "4f1d2c3b-0000-0000-0000-000000000001",
            "args": {"order_no": "A1"},
            "chain": ["parent-wf-id"],
        }
    ]


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
    ctx = _make_ctx(
        _services(llm, {"workflow_tool": fake}), config, {"react_only": True, "input": "q"}
    )
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
    ctx = _make_ctx(
        _services(llm, {"workflow_tool": fake}), config, {"react_only": True, "input": "q"}
    )
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

    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "knowledge_search_1", '{"query": "退款"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="已回答", usage=_Usage(2, 2)),
        ]
    )
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

    llm = _ScriptedLLM(
        [
            _Resp(
                content="", tool_calls=[_ToolCall("c1", "get_weather", "{}")], usage=_Usage(60, 50)
            ),
        ]
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tokenBudget": 100,
        "tools": [{"name": "get_weather", "description": "d", "parameters": {"type": "object"}}],
    }
    ctx = _make_ctx(
        _services(llm, {"tool_executor": executor}), config, {"react_only": True, "input": "q"}
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert touched == []
    assert result.outputs["finish_reason"] == "budget_exceeded"
    assert "预算已用尽" in result.outputs["output"]


def test_node_deep_mode_budget_after_reflect() -> None:
    """深度模式：execute 收敛 + reflect 未达标后累计超预算 → 不再跑下一轮 execute。"""
    plan = _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "g"}]}), usage=_Usage(30, 20))
    execute1 = _Resp(content="初步回答", usage=_Usage(20, 10))
    reflect1 = _Resp(
        content=json.dumps({"done": False, "suggestion": "继续"}), usage=_Usage(20, 20)
    )
    reflect2 = _Resp(content=json.dumps({"done": True}), usage=_Usage(1, 1))
    llm = _ScriptedLLM([plan, execute1, reflect1, execute1, reflect2])
    config = {"modleName": "m", "systemPrompt": "S", "tokenBudget": 100}
    ctx = _make_ctx(_services(llm), config, {"input": "q"})  # react_only 缺省 False → 深度模式
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["finish_reason"] == "budget_exceeded"
    # plan(50)+execute(30)+reflect(40)=120 ≥ 100 → reflect 后停，无第二次 execute 调用
    assert len(llm.calls) == 3
    assert result.outputs["output"] == "初步回答"


# ---------- M4-c F14.2/F14.3/F14.5：智能体委派合成与分派 ----------
class _FakeAgentTool:
    """AgentToolService 端口替身：记录 describe/invoke，返回可配置的合成结果。"""

    def __init__(
        self,
        described: dict | None = None,
        error: bool = False,
        name_map: dict[str, str] | None = None,
    ) -> None:
        self._described = described
        self._error = error
        self._name_map = name_map or {}
        self.describe_calls: list[dict] = []
        self.invoke_calls: list[dict] = []

    async def describe(
        self,
        application_id: str,
        chain: list[str],
        *,
        tool_name: str | None = None,
        description: str | None = None,
    ) -> dict | None:
        self.describe_calls.append(
            {
                "app": application_id,
                "chain": list(chain),
                "tool_name": tool_name,
                "description": description,
            }
        )
        if self._error:
            raise RuntimeError("目录不可用")
        if self._described is None:
            return None
        name = tool_name or self._name_map.get(application_id) or f"agent_{application_id[:8]}"
        return {
            "name": name,
            "description": f"把问题委派给专家处理。专长：{description or '默认专长'}",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        }

    async def invoke(self, application_id: str, arguments: dict, chain: list[str]) -> str:
        self.invoke_calls.append({"app": application_id, "args": arguments, "chain": list(chain)})
        return "专家答复：上限500元"


_AGENT_APP = "7b2e3d4c-0000-0000-0000-000000000002"


def _sub_agent_config(**entry_overrides: Any) -> dict:
    entry: dict[str, Any] = {"applicationId": _AGENT_APP, "mode": "delegate"}
    entry.update(entry_overrides)
    return {"modleName": "m", "systemPrompt": "S", "subAgents": [entry]}


def test_sub_agent_mount_synthesizes_tool_and_invokes() -> None:
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "agent_7b2e3d4c", '{"question": "报销上限"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="已委派完成", usage=_Usage(2, 2)),
        ]
    )
    runtime_input = {"react_only": True, "input": "问下专家", "workflow_chain": ["parent-wf-id"]}
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(description="差旅报销"),
        runtime_input,
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "已委派完成"
    spec = llm.calls[0]["tools"][0]
    assert spec.name == "agent_7b2e3d4c"
    assert spec.parameters["required"] == ["question"]
    # 配置覆盖值原样传给 describe（F14.1 toolName/description）
    assert fake.describe_calls == [
        {
            "app": _AGENT_APP,
            "chain": ["parent-wf-id"],
            "tool_name": None,
            "description": "差旅报销",
        }
    ]
    assert fake.invoke_calls == [
        {
            "app": _AGENT_APP,
            "args": {"question": "报销上限"},
            "chain": ["parent-wf-id"],
        }
    ]


def test_sub_agent_delegation_prompt_section_appended() -> None:
    """F14.5：有专家挂载时系统提示追加"可委派专家"段；无挂载逐字节不变。"""
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(),
        {"react_only": True, "input": "q"},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    system = llm.calls[0]["messages"][0]["content"]
    assert "## 可委派专家" in system and "agent_7b2e3d4c" in system

    llm_plain = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx_plain = _make_ctx(
        _services(llm_plain),
        {"modleName": "m", "systemPrompt": "S"},
        {"react_only": True, "input": "q"},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx_plain))
    assert llm_plain.calls[0]["messages"][0]["content"] == "S"


def test_sub_agent_self_reference_skipped() -> None:
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(applicationId="11111111-2222-3333-4444-555555555555"),
        {"react_only": True, "input": "q"},
        application_id="11111111-2222-3333-4444-555555555555",
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert (llm.calls[0]["tools"] or []) == []
    assert fake.describe_calls == []


def test_sub_agent_handoff_prompt_section_and_mixed_mounts() -> None:
    """T-c7：mode=handoff 进"可接管专家"段且不进"可委派专家"段；
    混合挂载两段并列，delegate 单独挂载时接管段不出现。"""
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(mode="handoff", description="票务"),
        {"react_only": True, "input": "q"},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    system = llm.calls[0]["messages"][0]["content"]
    assert "## 可接管专家" in system and "agent_7b2e3d4c" in system
    assert "可委派专家" not in system

    other_app = "9c9c9c9c-0000-0000-0000-000000000009"
    llm_mixed = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config_mixed = {
        "modleName": "m",
        "systemPrompt": "S",
        "subAgents": [
            {"applicationId": _AGENT_APP, "mode": "delegate"},
            {"applicationId": other_app, "mode": "handoff"},
        ],
    }
    ctx_mixed = _make_ctx(
        _services(llm_mixed, {"agent_tool": fake}),
        config_mixed,
        {"react_only": True, "input": "q"},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx_mixed))
    system_mixed = llm_mixed.calls[0]["messages"][0]["content"]
    assert "## 可委派专家" in system_mixed and "## 可接管专家" in system_mixed
    assert "agent_9c9c9c9c" in system_mixed


def test_sub_agent_handoff_synthesizes_declarative_tool_and_short_circuits() -> None:
    """T-c6：mode=handoff 合成声明性工具（describe 同 delegate 口径 + 接管注记），
    命中即整轮短路，经 outputs.handoff 透出；不进执行器分派（invoke 零调用）。"""
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "agent_7b2e3d4c", '{"question": "帮我订票"}')],
                usage=_Usage(1, 1),
            ),
        ]
    )
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(mode="handoff", description="票务"),
        {"react_only": True, "input": "q"},
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    spec = llm.calls[0]["tools"][0]
    assert spec.name == "agent_7b2e3d4c"
    assert "接管" in spec.description
    assert fake.invoke_calls == []
    handoff = result.outputs["handoff"]
    assert handoff["tool_name"] == "agent_7b2e3d4c"
    assert handoff["application_id"] == _AGENT_APP
    assert handoff["returned"] is False
    assert result.outputs["output"] == ""
    assert result.outputs["finish_reason"] == "handed_off"


def test_sub_agent_handoff_without_call_keeps_baseline_outputs() -> None:
    """声明了接管工具但模型没调用：outputs 不出现 handoff 键，收敛行为不变。"""
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(mode="handoff"),
        {"react_only": True, "input": "q"},
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert "handoff" not in result.outputs
    assert "finish_reason" not in result.outputs
    assert result.outputs["output"] == "done"


def test_hand_back_injected_on_inbound_target_side() -> None:
    """T-c6：ChatService 写 handoff_inbound 入参后，目标侧自动注入 hand_back
    声明工具，模型调用即透出 returned=True 的 handoff（handed_back）。"""
    llm = _ScriptedLLM(
        [
            _Resp(content="", tool_calls=[_ToolCall("c1", "hand_back", "{}")], usage=_Usage(1, 1)),
        ]
    )
    ctx = _make_ctx(
        _services(llm),
        {"modleName": "m", "systemPrompt": "S"},
        {
            "react_only": True,
            "input": "已办结",
            "handoff_inbound": {"from_application_id": _AGENT_APP},
        },
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert [spec.name for spec in llm.calls[0]["tools"]] == ["hand_back"]
    assert result.outputs["handoff"]["returned"] is True
    assert result.outputs["handoff"]["tool_name"] == "hand_back"
    assert result.outputs["finish_reason"] == "handed_back"

    llm_plain = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx_plain = _make_ctx(
        _services(llm_plain),
        {"modleName": "m", "systemPrompt": "S"},
        {"react_only": True, "input": "q"},
    )
    plain_result = asyncio.run(AgentLoopNodeHandler().run(ctx_plain))
    assert (llm_plain.calls[0]["tools"] or []) == []
    assert "handoff" not in plain_result.outputs


def test_deep_mode_handoff_skips_reflect() -> None:
    """深度模式 execute 命中接管：短路整个 reflect 循环，不再支付评审成本。"""
    fake = _FakeAgentTool(described={})
    plan = _Resp(content=json.dumps({"tasks": [{"id": "t1", "goal": "g"}]}), usage=_Usage(1, 1))
    execute = _Resp(
        content="",
        tool_calls=[_ToolCall("c1", "agent_7b2e3d4c", '{"question": "q"}')],
        usage=_Usage(1, 1),
    )
    reflect = _Resp(content=json.dumps({"done": False, "suggestion": "继续"}), usage=_Usage(1, 1))
    llm = _ScriptedLLM([plan, execute, reflect])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(mode="handoff"),
        {"input": "q"},  # react_only 缺省 False → 深度模式
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert result.outputs["handoff"]["application_id"] == _AGENT_APP
    assert result.outputs["finish_reason"] == "handed_off"
    # 仅 plan + execute 两次 LLM 调用，reflect 不复跑
    assert len(llm.calls) == 2
    assert result.outputs["reflect_history"] == []


def test_sub_agents_over_limit_truncated() -> None:
    fake = _FakeAgentTool(described={})
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "subAgents": [
            {"applicationId": f"aa00000{i}00-0000-0000-0000-000000000000", "mode": "delegate"}
            for i in range(1, 7)
        ],
    }
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}), config, {"react_only": True, "input": "q"}
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert len(fake.describe_calls) == 5
    assert len(llm.calls[0]["tools"] or []) == 5


def test_sub_agent_duplicate_name_skipped(monkeypatch) -> None:
    """合成名与既有工具重名：跳过并告警，不产生互相覆盖的白名单项（F14.3）。"""
    fake = _FakeAgentTool(
        described={},
        name_map={
            "aaaaaaaa-0000-0000-0000-000000000001": "agent_dup",
            "aaaaaaaa-0000-0000-0000-000000000002": "agent_dup",
        },
    )
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "subAgents": [
            {"applicationId": "aaaaaaaa-0000-0000-0000-000000000001", "mode": "delegate"},
            {"applicationId": "aaaaaaaa-0000-0000-0000-000000000002", "mode": "delegate"},
        ],
    }
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}), config, {"react_only": True, "input": "q"}
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert [spec.name for spec in llm.calls[0]["tools"] or []] == ["agent_dup"]


def test_mcp_tool_cannot_shadow_agent_prefix(monkeypatch, mcp_calls) -> None:
    """agent_ 为合成保留前缀（F14.3）：MCP 快照同名项跳过。"""
    server = {
        "serverUrl": "http://10.0.0.9:9000/mcp",
        "enabledTools": [{"name": "agent_sneaky", "description": "d", "inputSchema": None}],
    }
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    config = {"modleName": "m", "systemPrompt": "S", "mcpServers": [server]}
    ctx = _make_ctx(_services(llm), config, {"react_only": True, "input": "q"})
    asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert (llm.calls[0]["tools"] or []) == []


def test_agent_describe_unavailable_skipped() -> None:
    fake = _FakeAgentTool(described=None)
    llm = _ScriptedLLM([_Resp(content="done", usage=_Usage(1, 1))])
    ctx = _make_ctx(
        _services(llm, {"agent_tool": fake}),
        _sub_agent_config(),
        {"react_only": True, "input": "q"},
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))
    assert (llm.calls[0]["tools"] or []) == []
    assert result.outputs["output"] == "done"
