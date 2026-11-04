"""T12：Subworkflow 节点（type=9）单测。

验证：
- 缺 workflowId 时返回错误 outputs。
- 未注册 subgraph_loader 时返回 stub。
- 注册 async subgraph_loader 时，handler 能正确 await 并执行子图。
- loader 返回空时返回错误 outputs。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.canvas.convert import convert_canvas
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.subworkflow import SubworkflowNodeHandler


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="sub-test-thread",
        application_id=uuid4(),
    )


def test_subworkflow_missing_workflow_id_returns_error() -> None:
    ctx = NodeContext(
        node_id="sub_1",
        node_type=NodeType.SUB_WORKFLOW.value,
        inputs={},
        config={},
        env=_make_env(),
        services=ServiceRegistry(),
    )
    result = asyncio.run(SubworkflowNodeHandler().run(ctx))
    assert "error" in result.outputs


def test_subworkflow_without_loader_returns_stub() -> None:
    ctx = NodeContext(
        node_id="sub_1",
        node_type=NodeType.SUB_WORKFLOW.value,
        inputs={},
        config={"workflowId": str(uuid4())},
        env=_make_env(),
        services=ServiceRegistry(),
    )
    result = asyncio.run(SubworkflowNodeHandler().run(ctx))
    assert result.outputs["input"].startswith("[SUBWORKFLOW stub]")


def test_subworkflow_async_loader_executes_child_graph() -> None:
    """async loader（debug 路由 / user chat 路由注册的形式）能被正确 await 并执行。"""
    child_id = str(uuid4())
    child_canvas: dict[str, Any] = {
        "nodes": [
            {
                "id": "c_start",
                "type": "1",
                "data": {
                    "nodeMeta": {"title": "子开始"},
                    "inputs": {},
                    "outputs": [{"name": "echo", "type": "string"}],
                },
            },
            {
                "id": "c_end",
                "type": "2",
                "data": {
                    "nodeMeta": {"title": "子结束"},
                    "inputs": {
                        "inputParameters": [
                            {
                                "name": "echo",
                                "input": {
                                    "type": "string",
                                    "value": {"type": "literal", "content": "hello-from-child"},
                                },
                            }
                        ]
                    },
                },
            },
        ],
        "edges": [
            {"sourceNodeID": "c_start", "targetNodeID": "c_end", "sourcePortID": "source"},
        ],
    }

    async def fake_loader(workflow_id: str) -> dict:
        assert workflow_id == child_id
        return child_canvas

    services = ServiceRegistry()
    services.register("subgraph_loader", fake_loader)

    ctx = NodeContext(
        node_id="sub_1",
        node_type=NodeType.SUB_WORKFLOW.value,
        inputs={},
        config={"workflowId": child_id},
        env=_make_env(),
        services=services,
    )
    result = asyncio.run(SubworkflowNodeHandler().run(ctx))
    # 子图 END 节点把 echo 输出作为子图 output
    assert result.outputs.get("echo") == "hello-from-child"


def test_subworkflow_loader_returns_empty_returns_error() -> None:
    async def fake_loader(_workflow_id: str) -> dict:
        return {}

    services = ServiceRegistry()
    services.register("subgraph_loader", fake_loader)

    ctx = NodeContext(
        node_id="sub_1",
        node_type=NodeType.SUB_WORKFLOW.value,
        inputs={},
        config={"workflowId": str(uuid4())},
        env=_make_env(),
        services=services,
    )
    result = asyncio.run(SubworkflowNodeHandler().run(ctx))
    assert "error" in result.outputs
