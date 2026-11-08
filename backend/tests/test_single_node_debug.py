"""单节点试运行（B-N9-03）单元测试：不连数据库。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from internal.domain.canvas.convert import convert_canvas
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import RuntimeEnv, ServiceRegistry
from internal.domain.graph.runtime import GraphRuntime

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="debug-node-thread",
        application_id=uuid4(),
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_execute_node_only_start_node() -> None:
    """START 单节点：画布无入参表达式，试运行表单入参原样作为 outputs。"""
    graph = convert_canvas(_load("start_exit.json"))
    node = graph.node_by_id("100001")
    compiler = Compiler(services=ServiceRegistry())

    result = _run(compiler.execute_node_only(node, _make_env(), {"USER_INPUT": "单节点"}))

    assert result["error"] is None
    assert result["outputs"]["USER_INPUT"] == "单节点"


def test_execute_node_only_override_wins_over_ref() -> None:
    """END 节点的 output 引用未执行上游；表单覆盖值优先于空引用。"""
    graph = convert_canvas(_load("start_exit.json"))
    node = graph.node_by_id("900001")
    compiler = Compiler(services=ServiceRegistry())

    result = _run(compiler.execute_node_only(node, _make_env(), {"output": "手动覆盖"}))

    assert result["error"] is None
    assert result["outputs"]["output"] == "手动覆盖"


def test_runtime_invoke_node_returns_metrics() -> None:
    """GraphRuntime.invoke_node 返回节点信息、状态与耗时，且不写 run 记录。"""
    runtime = GraphRuntime(
        canvas_json=_load("start_exit.json"),
        services=ServiceRegistry(),
        checkpointer=None,
    )

    result = _run(runtime.invoke_node("100001", {"USER_INPUT": "hello"}))

    assert result["node_id"] == "100001"
    assert result["node_type"] == "1"
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["duration_ms"] >= 0
    assert result["outputs"]["USER_INPUT"] == "hello"


def test_runtime_invoke_node_unknown_node() -> None:
    """节点 ID 不存在时抛 ValueError，交由路由转成 400。"""
    runtime = GraphRuntime(
        canvas_json=_load("start_exit.json"),
        services=ServiceRegistry(),
        checkpointer=None,
    )

    with pytest.raises(ValueError, match="画布不存在节点"):
        _run(runtime.invoke_node("not-exists", {}))
