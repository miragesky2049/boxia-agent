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
    def __init__(
        self, content: str, tool_calls: list | None = None, usage: _Usage | None = None
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.usage = usage or _Usage()


class _ScriptedLLM:
    """按脚本顺序返回响应，记录每次调用参数。"""

    def __init__(self, script: list[_Resp]) -> None:
        self._script = script
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, response_format=None, **kwargs) -> _Resp:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "response_format": response_format,
                "model": kwargs.get("model"),
                "context": kwargs.get("context"),
            }
        )
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return self._script[idx]


def _make_ctx(services: ServiceRegistry, config: dict, user_input: str) -> NodeContext:
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
        inputs={"input": user_input},
        config=config,
        env=env,
        services=services,
    )


def test_agent_loop_plan_execute_reflect_done_first_pass() -> None:
    """Plan 输出任务清单，Execute 首轮回答，Reflect 直接 done=true。"""
    script = [
        # PLAN
        _Resp(
            content=json.dumps({"tasks": [{"id": "t1", "goal": "回答问题", "acceptance": "简短"}]}),
            usage=_Usage(10, 5),
        ),
        # EXECUTE（第一轮即最终答案）
        _Resp(content="北京今天 20 度。", usage=_Usage(20, 10)),
        # REFLECT
        _Resp(
            content=json.dumps({"done": True, "critique": "", "suggestion": ""}), usage=_Usage(5, 2)
        ),
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
        _Resp(
            content=json.dumps({"tasks": [{"id": "t1", "goal": "算和", "acceptance": "给出数字"}]}),
            usage=_Usage(5, 2),
        ),
        # EXECUTE 1
        _Resp(content="1+2=4（错）", usage=_Usage(10, 3)),
        # REFLECT 1：指出错误
        _Resp(
            content=json.dumps({"done": False, "critique": "结果不对", "suggestion": "重新计算"}),
            usage=_Usage(3, 2),
        ),
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
        _Resp(
            content="",
            tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')],
            usage=_Usage(8, 4),
        ),
        # EXECUTE 第二轮：拿到 tool 结果后最终回答
        _Resp(content="北京 20 度。", usage=_Usage(15, 6)),
        # REFLECT
        _Resp(content=json.dumps({"done": True}), usage=_Usage(3, 1)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    ctx = _make_ctx(
        services,
        {
            "modleName": "m",
            "tools": [
                {
                    "name": "get_weather",
                    "description": "天气",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        },
        "北京天气",
    )
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
        _Resp(
            content="",
            tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')],
            usage=_Usage(1, 1),
        ),
        _Resp(content="北京晴。", usage=_Usage(2, 2)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    config = {
        "modleName": "m1",
        "systemPrompt": "S",
        "maxToolRounds": 1,
        "tools": [
            {
                "name": "get_weather",
                "description": "天气",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
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
    assert [m["role"] for m in first_call["messages"][:4]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "任务清单" not in first_call["messages"][0]["content"]
    assert first_call["messages"][3]["content"] == "天气怎么样"


def test_agent_loop_react_only_dict_context_restored() -> None:
    """20261106 review 修正：chat 入参以 to_storage_dict 平铺形态进画布（run 表
    JSONB 约束），节点内还原为 AgentRunContext 再透传给 LLM。"""
    tenant_id, agent_id, user_id = uuid4(), uuid4(), uuid4()
    expected = AgentRunContext(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id="conv-1",
        run_id="run-fixed",
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
    assert (restored.agent_id, restored.tenant_id, restored.user_id) == (
        agent_id,
        tenant_id,
        user_id,
    )
    assert restored.conversation_id == "conv-1" and restored.run_id == "run-fixed"


def test_agent_loop_react_only_trace_events_carry_chat_mapping_fields() -> None:
    """trace 事件 additive 补齐 chat SSE 映射所需字段（旧字段保持不变）。"""
    events: list[tuple[str, dict]] = []

    async def _emit(etype: str, payload: dict) -> None:
        events.append((etype, payload))

    def _tool_executor(name: str, args: dict) -> str:
        return "晴，20 度"

    script = [
        _Resp(
            content="",
            tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')],
            usage=_Usage(3, 4),
        ),
        _Resp(content="北京 20 度。", usage=_Usage(5, 6)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry({"llm": llm, "tool_executor": _tool_executor})

    ctx = _make_runtime_ctx(
        services,
        {
            "modleName": "m",
            "systemPrompt": "S",
            "tools": [{"name": "get_weather", "parameters": {"type": "object", "properties": {}}}],
        },
        {"react_only": True, "input": "北京天气"},
        emit=_emit,
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    start = next(
        p
        for t, p in events
        if t == "prompt_text" and p.get("phase") == "execute" and "messages" in p
    )
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


# ---------- 20261107 0074 PRD F5：知识库即工具（datasets）----------
class _FakeChunk:
    # 与 domain/retrieval/model.Chunk 契约字段对齐（F5.3 溯源需要 chunk_id/dataset_id）
    def __init__(self, content: str) -> None:
        self.content = content
        self.metadata: dict = {}
        self.chunk_id = "c-1"
        self.dataset_id = "d-1"
        self.document_id = "doc-1"


class _FakeSearchResult:
    def __init__(self, content: str, score: float) -> None:
        self.chunk = _FakeChunk(content)
        self.score = score


class _FakeEmbedding:
    def __init__(self) -> None:
        self.texts: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeVectorStore:
    def __init__(
        self, results: dict[str, list[_FakeSearchResult]] | None = None, error: bool = False
    ) -> None:
        self.results = results or {}
        self.error = error
        self.searches: list[dict] = []

    async def search(self, *, dataset_id, query_vector, top_k, tenant_id):
        self.searches.append(
            {
                "dataset_id": dataset_id,
                "query_vector": query_vector,
                "top_k": top_k,
                "tenant_id": tenant_id,
            }
        )
        if self.error:
            raise RuntimeError("向量库不可用")
        return self.results.get(dataset_id, [])


def _knowledge_services(llm_script: list[_Resp], store: _FakeVectorStore) -> dict:
    llm = _ScriptedLLM(llm_script)
    services = ServiceRegistry({"llm": llm, "embedding": _FakeEmbedding(), "vector_store": store})
    return {"llm": llm, "services": services, "store": store}


def test_agent_loop_datasets_on_demand_synthesizes_knowledge_tool() -> None:
    """onDemand 库合成 knowledge_search_1 工具：模型发起检索 → 走向量库 → 结果回灌。"""
    store = _FakeVectorStore({"d1": [_FakeSearchResult("退款需在7天内申请", 0.912)]})
    kit = _knowledge_services(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "knowledge_search_1", '{"query": "退款期限"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="退款需在7天内申请。", usage=_Usage(2, 2)),
        ],
        store,
    )
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "datasets": [{"datasetId": "d1", "name": "售后手册", "mode": "onDemand", "topK": 3}],
    }
    ctx = _make_runtime_ctx(
        kit["services"], config, {"react_only": True, "input": "退款期限是多久"}
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "退款需在7天内申请。"
    # 合成工具进白名单与 schema（description 带库名，帮助模型路由）
    tool_names = [spec.name for spec in (kit["llm"].calls[0]["tools"] or [])]
    assert tool_names == ["knowledge_search_1"]
    assert "售后手册" in kit["llm"].calls[0]["tools"][0].description
    # 检索走 dataset_id/top_k/tenant_id，query 用模型给的检索词
    assert store.searches[0]["dataset_id"] == "d1"
    assert store.searches[0]["top_k"] == 3
    assert store.searches[0]["tenant_id"] == str(ctx.env.tenant_id)
    # 检索结果以 tool 消息回灌（带相关性序号格式）
    second_messages = kit["llm"].calls[1]["messages"]
    tool_msg = next(m for m in second_messages if m["role"] == "tool")
    assert "退款需在7天内申请" in tool_msg["content"]
    assert "相关性 0.912" in tool_msg["content"]


def test_agent_loop_datasets_index_skips_invalid_entries() -> None:
    """缺 datasetId 的条目被跳过，合法条目按解析后序号命名（保持配置序稳定）。"""
    store = _FakeVectorStore()
    kit = _knowledge_services(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "knowledge_search_1", '{"query": "x"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="完成。", usage=_Usage(1, 1)),
        ],
        store,
    )
    config = {
        "modleName": "m",
        "datasets": [{"mode": "onDemand"}, {"datasetId": "d9", "mode": "onDemand"}],
    }
    ctx = _make_runtime_ctx(kit["services"], config, {"react_only": True, "input": "问题"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "完成。"
    assert store.searches[0]["dataset_id"] == "d9"


def test_agent_loop_datasets_always_injects_reference_into_system() -> None:
    """always 库：执行前自动检索并拼进 system 参考资料段，不合成工具。"""
    store = _FakeVectorStore({"d2": [_FakeSearchResult("产品支持蓝牙5.3", 0.88)]})
    kit = _knowledge_services([_Resp(content="支持蓝牙5.3。", usage=_Usage(1, 1))], store)
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "datasets": [{"datasetId": "d2", "name": "产品库", "mode": "always"}],
    }
    ctx = _make_runtime_ctx(kit["services"], config, {"react_only": True, "input": "支持蓝牙吗"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "支持蓝牙5.3。"
    assert store.searches[0]["dataset_id"] == "d2"
    # always 用用户原问题直接检索
    assert store.searches[0]["dataset_id"] == "d2" and kit["llm"].calls[0]["tools"] is None
    system_content = kit["llm"].calls[0]["messages"][0]["content"]
    assert system_content.startswith("S")
    assert "参考资料" in system_content and "【产品库】" in system_content
    assert "产品支持蓝牙5.3" in system_content


def test_agent_loop_datasets_always_failure_does_not_break_chat() -> None:
    """always 检索失败：跳过注入，对话照常完成。"""
    store = _FakeVectorStore(error=True)
    kit = _knowledge_services([_Resp(content="照常回答。", usage=_Usage(1, 1))], store)
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "datasets": [{"datasetId": "d3", "mode": "always"}],
    }
    ctx = _make_runtime_ctx(kit["services"], config, {"react_only": True, "input": "你好"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "照常回答。"
    assert "参考资料" not in kit["llm"].calls[0]["messages"][0]["content"]


def test_agent_loop_knowledge_executor_delegates_other_tools() -> None:
    """合成执行器包装后：非检索工具仍委托租户目录执行器。"""
    executed: list[str] = []

    def _base(name: str, args: dict) -> str:
        executed.append(name)
        return "晴，20 度"

    store = _FakeVectorStore({"d1": [_FakeSearchResult("退款7天内", 0.9)]})
    script = [
        _Resp(
            content="",
            tool_calls=[_ToolCall("c1", "get_weather", '{"city": "北京"}')],
            usage=_Usage(1, 1),
        ),
        _Resp(
            content="",
            tool_calls=[_ToolCall("c2", "knowledge_search_1", '{"query": "退款"}')],
            usage=_Usage(1, 1),
        ),
        _Resp(content="北京晴，退款7天内。", usage=_Usage(1, 1)),
    ]
    llm = _ScriptedLLM(script)
    services = ServiceRegistry(
        {
            "llm": llm,
            "tool_executor": _base,
            "embedding": _FakeEmbedding(),
            "vector_store": store,
        }
    )
    config = {
        "modleName": "m",
        "tools": [
            {
                "name": "get_weather",
                "description": "天气",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "datasets": [{"datasetId": "d1", "mode": "onDemand"}],
    }
    ctx = _make_runtime_ctx(services, config, {"react_only": True, "input": "天气和退款"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "北京晴，退款7天内。"
    assert executed == ["get_weather"]
    assert store.searches[0]["dataset_id"] == "d1"


def test_agent_loop_knowledge_missing_services_yields_error_observation() -> None:
    """检索服务未注册：模型调用 knowledge_search 得到 [error] observation，循环不中断。"""
    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "knowledge_search_1", '{"query": "x"}')],
                usage=_Usage(1, 1),
            ),
            _Resp(content="抱歉，暂时查不到。", usage=_Usage(1, 1)),
        ]
    )
    services = ServiceRegistry({"llm": llm})
    config = {
        "modleName": "m",
        "datasets": [{"datasetId": "d1", "mode": "onDemand"}],
    }
    ctx = _make_runtime_ctx(services, config, {"react_only": True, "input": "问题"})
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "抱歉，暂时查不到。"
    tool_msg = next(m for m in llm.calls[1]["messages"] if m["role"] == "tool")
    assert tool_msg["content"].startswith("[error]")


# ---------- 0074 PRD F10/F9（M3）：工具审批快照暂停/续跑 + 多模态 ----------
def _pending_assistant_messages(name: str = "send_email", call_id: str = "c1") -> list[dict]:
    """F10 快照形态：末条 assistant 带未回答 tool_calls。"""
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
                    "function": {"name": name, "arguments": '{"to": "boss"}'},
                }
            ],
        },
    ]


def test_agent_loop_awaiting_approval_outputs_snapshot() -> None:
    """敏感工具轮：节点不执行工具，提前返回 awaiting_approval + 执行快照。"""

    def executor(name: str, args: dict) -> str:
        raise AssertionError("挂起轮不得执行工具")

    llm = _ScriptedLLM(
        [
            _Resp(
                content="",
                tool_calls=[_ToolCall("c1", "send_email", '{"to": "boss"}')],
                usage=_Usage(2, 3),
            ),
        ]
    )
    services = ServiceRegistry({"llm": llm, "tool_executor": executor})
    events: list[tuple[str, dict]] = []

    async def _emit(etype: str, payload: dict) -> None:
        events.append((etype, payload))

    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tools": [
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "sensitiveTools": [{"name": "send_email"}],
    }
    ctx = _make_runtime_ctx(
        services,
        config,
        {"react_only": True, "input": "发邮件给老板"},
        emit=_emit,
    )
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    outputs = result.outputs
    assert outputs["awaiting_approval"] is True
    approval = outputs["approval"]
    assert approval["type"] == "tool_approval"
    assert approval["node_id"] == "agent_1"
    assert [c["id"] for c in approval["awaiting_calls"]] == ["c1"]
    snapshot = outputs["snapshot"]
    assert snapshot["messages"][-1]["role"] == "assistant"
    assert snapshot["messages"][-1]["tool_calls"][0]["id"] == "c1"
    assert snapshot["reflect_round"] == 0 and snapshot["plan_tasks"] == []
    assert snapshot["usage"]["total_tokens"] == 5
    assert result.usage["total_tokens"] == 5
    # trace 透出挂起事件供运行详情页展示
    assert any(t == "tool_approval_required" for t, _ in events)


def _approval_snapshot() -> dict:
    return {
        "messages": _pending_assistant_messages(),
        "plan_tasks": [],
        "reflect_round": 0,
        "reflect_history": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_agent_loop_resume_approved_executes_pending_round() -> None:
    """批准续跑：跳过 PLAN、排空快照轮、usage 跨挂起累计。"""
    executed: list[tuple[str, dict]] = []

    def executor(name: str, args: dict) -> str:
        executed.append((name, args))
        return "邮件已送达"

    llm = _ScriptedLLM([_Resp(content="已发送并汇报。", usage=_Usage(1, 1))])
    services = ServiceRegistry({"llm": llm, "tool_executor": executor})
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tools": [
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "sensitiveTools": [{"name": "send_email"}],
    }
    runtime_input = {
        "react_only": True,
        "input": "批准执行工具调用",
        "approval_resume": {"approved": True, "comment": "", "snapshot": _approval_snapshot()},
    }
    ctx = _make_runtime_ctx(services, config, runtime_input)
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs.get("awaiting_approval") is None
    assert result.outputs["output"] == "已发送并汇报。"
    assert executed == [("send_email", {"to": "boss"})]
    # 快照续跑不重做计划：仅排空后的收敛一次 LLM 调用
    assert len(llm.calls) == 1
    # usage 基线来自快照（15）+ 续跑 2
    assert result.usage["total_tokens"] == 17


def test_agent_loop_resume_rejected_does_not_execute() -> None:
    """拒绝续跑：pending 调用回灌拒绝 observation，不触达执行器。"""

    def executor(name: str, args: dict) -> str:
        raise AssertionError("拒绝的调用不得执行")

    llm = _ScriptedLLM([_Resp(content="好的，改用现有信息回答。", usage=_Usage(1, 1))])
    services = ServiceRegistry({"llm": llm, "tool_executor": executor})
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tools": [
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "sensitiveTools": [{"name": "send_email"}],
    }
    runtime_input = {
        "react_only": True,
        "input": "拒绝执行工具调用（理由：先别发）",
        "approval_resume": {
            "approved": False,
            "comment": "先别发",
            "snapshot": _approval_snapshot(),
        },
    }
    ctx = _make_runtime_ctx(services, config, runtime_input)
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "好的，改用现有信息回答。"
    tool_msg = next(m for m in llm.calls[0]["messages"] if m["role"] == "tool")
    assert "用户拒绝了该工具调用" in tool_msg["content"]


def test_agent_loop_deep_resume_continues_reflect_round() -> None:
    """深度模式快照续跑：跳过 PLAN，从快照 reflect_round 继续 execute→reflect。"""

    def executor(name: str, args: dict) -> str:
        return "邮件已送达"

    snapshot = _approval_snapshot()
    snapshot["plan_tasks"] = [{"id": "t1", "goal": "发邮件"}]
    llm = _ScriptedLLM(
        [
            # execute 收敛（排空轮后）
            _Resp(content="已处理。", usage=_Usage(1, 1)),
            # reflect done
            _Resp(content=json.dumps({"done": True}), usage=_Usage(1, 1)),
        ]
    )
    services = ServiceRegistry({"llm": llm, "tool_executor": executor})
    config = {
        "modleName": "m",
        "systemPrompt": "S",
        "tools": [
            {
                "name": "send_email",
                "description": "发信",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "sensitiveTools": [{"name": "send_email"}],
    }
    runtime_input = {
        "input": "批准执行工具调用",
        "approval_resume": {"approved": True, "comment": "", "snapshot": snapshot},
    }
    ctx = _make_runtime_ctx(services, config, runtime_input)
    result = asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert result.outputs["output"] == "已处理。"
    assert result.outputs["plan"] == [{"id": "t1", "goal": "发邮件"}]
    assert len(result.outputs["reflect_history"]) == 1
    # 无 plan 调用：任务规划器提示词不得出现在任何一次 messages 里
    assert all(
        "任务规划器" not in str(m.get("content", ""))
        for call in llm.calls
        for m in call["messages"]
    )


def test_agent_loop_vision_enabled_builds_multimodal_user_content() -> None:
    """visionEnabled=true + 入参 images：user 消息为 OpenAI multi-modal parts 数组。"""
    llm = _ScriptedLLM([_Resp(content="图里有只猫。", usage=_Usage(1, 1))])
    services = ServiceRegistry({"llm": llm})
    config = {"modleName": "m", "systemPrompt": "S", "visionEnabled": True}
    ctx = _make_runtime_ctx(
        services,
        config,
        {"react_only": True, "input": "看图", "images": ["http://img/a.png"]},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    user_msg = llm.calls[0]["messages"][-1]
    assert user_msg["content"] == [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "http://img/a.png"}},
    ]


def test_agent_loop_vision_disabled_ignores_images() -> None:
    """visionEnabled 缺省/false：图片入参被忽略，user content 保持纯文本。"""
    llm = _ScriptedLLM([_Resp(content="纯文本回答。", usage=_Usage(1, 1))])
    services = ServiceRegistry({"llm": llm})
    config = {"modleName": "m", "systemPrompt": "S"}
    ctx = _make_runtime_ctx(
        services,
        config,
        {"react_only": True, "input": "你好", "images": ["http://img/a.png"]},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert llm.calls[0]["messages"][-1]["content"] == "你好"


def test_agent_loop_summary_injected_as_system_block() -> None:
    """M4 PRD F15.5：start_inputs.summary 存在时，摘要作独立 system 段插在
    角色设定之后、历史原文之前（与进程内通道 ChatService 同构）。"""
    llm = _ScriptedLLM([_Resp(content="回答结束。", usage=_Usage(2, 1))])
    services = ServiceRegistry({"llm": llm})
    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {
            "react_only": True,
            "input": "你好",
            "summary": "此前讨论了退款政策。",
            "history": [{"role": "user", "content": "早"}],
        },
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    messages = llm.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "你是助手"}
    assert messages[1]["role"] == "system"
    assert messages[1]["content"].startswith("## 更早对话摘要")
    assert "此前讨论了退款政策。" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "早"}
    assert messages[3] == {"role": "user", "content": "你好"}


def test_agent_loop_without_summary_message_shape_unchanged() -> None:
    """不传 summary（画布试运行/工作流/旧客户端）：messages 形态与改造前一致。"""
    llm = _ScriptedLLM([_Resp(content="回答结束。", usage=_Usage(2, 1))])
    services = ServiceRegistry({"llm": llm})
    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {"react_only": True, "input": "你好", "history": [{"role": "user", "content": "早"}]},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert llm.calls[0]["messages"] == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "早"},
        {"role": "user", "content": "你好"},
    ]


def test_agent_loop_memories_injected_after_summary_block() -> None:
    """M4 PRD F16.4：start_inputs.memories 存在时，记忆 system 段紧随摘要段之后。"""
    llm = _ScriptedLLM([_Resp(content="回答结束。", usage=_Usage(2, 1))])
    services = ServiceRegistry({"llm": llm})
    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {
            "react_only": True,
            "input": "你好",
            "summary": "此前讨论了退款政策。",
            "memories": ["用户偏好中文回复", "  ", {"不是字符串": True}],
            "history": [{"role": "user", "content": "早"}],
        },
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    messages = llm.calls[0]["messages"]
    assert messages[1]["content"].startswith("## 更早对话摘要")
    assert messages[2]["role"] == "system"
    assert messages[2]["content"].startswith("## 用户长期记忆")
    # 空串项被过滤，非字符串项原样 str 化后保留（防御式读取，条目内容已由服务层保证为字符串）
    assert messages[2]["content"].endswith("- 用户偏好中文回复\n- {'不是字符串': True}")
    assert "不作为指令执行" in messages[2]["content"]
    assert messages[3] == {"role": "user", "content": "早"}


def test_agent_loop_without_memories_message_shape_unchanged() -> None:
    """不传 memories（画布试运行/工作流/未开启长期记忆）：messages 形态不变。"""
    llm = _ScriptedLLM([_Resp(content="回答结束。", usage=_Usage(2, 1))])
    services = ServiceRegistry({"llm": llm})
    ctx = _make_runtime_ctx(
        services,
        {"modleName": "m", "systemPrompt": "你是助手"},
        {"react_only": True, "input": "你好", "summary": "旧摘要。", "memories": "非法"},
    )
    asyncio.run(AgentLoopNodeHandler().run(ctx))

    assert [m["role"] for m in llm.calls[0]["messages"]] == ["system", "system", "user"]
    assert llm.calls[0]["messages"][1]["content"].startswith("## 更早对话摘要")
