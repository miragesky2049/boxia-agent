"""新建应用默认画布：结构合法且可执行。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from internal.application.apps.application_service import _default_graph
from internal.domain.canvas.validate import validate_raw_graph
from internal.domain.graph.runtime import GraphRuntime


@pytest.mark.parametrize("flow_type", ["workflow", "chatflow", "agent"])
def test_default_graph_is_valid(flow_type):
    graph = _default_graph(flow_type, "test-model")
    errors = [i for i in validate_raw_graph(graph) if i.severity == "error"]
    assert errors == []


def test_workflow_default_graph_runs():
    runtime = GraphRuntime(
        canvas_json=_default_graph("workflow", "test-model"),
        tenant_id=uuid4(),
        checkpointer=InMemorySaver(),
    )
    output = asyncio.run(runtime.invoke({}))
    assert output == {"output": "运行完成"}


def test_chatflow_default_graph_runs_with_stub_llm():
    runtime = GraphRuntime(
        canvas_json=_default_graph("chatflow", "test-model"),
        tenant_id=uuid4(),
        checkpointer=InMemorySaver(),
        conversation_id=uuid4(),
    )
    output = asyncio.run(runtime.invoke({"USER_INPUT": "你好"}))
    assert output.get("output")


def test_agent_default_graph_runs_with_stub_llm():
    """0074：agent 默认画布 start→agent_loop→end，无 LLM 服务时节点 stub 仍能出话。"""
    runtime = GraphRuntime(
        canvas_json=_default_graph("agent", "test-model"),
        tenant_id=uuid4(),
        checkpointer=InMemorySaver(),
    )
    output = asyncio.run(runtime.invoke({"USER_INPUT": "你好"}))
    assert "[AgentLoop stub]" in str(output.get("output"))
