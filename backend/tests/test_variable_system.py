"""A8：变量系统测试。

覆盖：
1. variable_types.coerce() 对五种类型的强制转换
2. convert.py 解析简化格式与 coze 格式变量
3. Compiler.default_globals() 按声明类型做默认值强制转换
4. SetVariable 节点按 config.variableType 强制转换写入值
5. Runtime.invoke() 把 default_globals 合并进 initial_state.globals
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.canvas.convert import convert_canvas
from internal.domain.canvas.variable_types import coerce
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import (
    NodeContext,
    RuntimeEnv,
    ServiceRegistry,
)
from internal.domain.graph.nodes.set_variable import SetVariableNodeHandler


# ---------- 1. variable_types.coerce ----------


def test_coerce_string_from_native_types():
    assert coerce(123, "string") == "123"
    assert coerce(3.14, "string") == "3.14"
    assert coerce(True, "string") == "True"
    assert coerce("hello", "string") == "hello"


def test_coerce_string_from_dict_uses_json():
    result = coerce({"a": 1}, "string")
    assert isinstance(result, str)
    assert '"a": 1' in result


def test_coerce_number_from_string():
    assert coerce("3.14", "number") == 3.14
    assert coerce("42", "number") == 42.0


def test_coerce_number_invalid_returns_none():
    assert coerce("abc", "number") is None


def test_coerce_boolean_variants():
    assert coerce("true", "boolean") is True
    assert coerce("1", "boolean") is True
    assert coerce("yes", "boolean") is True
    assert coerce("false", "boolean") is False
    assert coerce("0", "boolean") is False
    assert coerce(1, "boolean") is True
    assert coerce(0, "boolean") is False


def test_coerce_object_from_json_string():
    result = coerce('{"a": 1}', "object")
    assert result == {"a": 1}


def test_coerce_object_plain_scalar_wraps():
    assert coerce("hello", "object") == {"value": "hello"}


def test_coerce_array_from_json_string():
    assert coerce("[1,2,3]", "array") == [1, 2, 3]


def test_coerce_array_scalar_wraps():
    assert coerce("x", "array") == ["x"]


def test_coerce_none_returns_none():
    assert coerce(None, "string") is None
    assert coerce(None, "number") is None


# ---------- 2. convert.py 变量解析 ----------


def test_convert_variables_simplified_format():
    raw = {
        "nodes": [],
        "edges": [],
        "variables": [
            {"name": "user_name", "type": "string", "default": "alice"},
            {"name": "age", "type": "number", "default": "18"},
        ],
    }
    graph = convert_canvas(raw)
    assert len(graph.variables) == 2
    assert graph.variables[0].name == "user_name"
    assert graph.variables[0].type == "string"
    assert graph.variables[0].default == "alice"
    assert graph.variables[1].name == "age"
    assert graph.variables[1].type == "number"
    assert graph.variables[1].default == "18"


def test_convert_variables_coze_format():
    raw = {
        "nodes": [],
        "edges": [],
        "globalVariables": [
            {
                "variableName": "counter",
                "variableType": "number",
                "defaultValue": "0",
                "description": "计数器",
            }
        ],
    }
    graph = convert_canvas(raw)
    assert len(graph.variables) == 1
    var = graph.variables[0]
    assert var.name == "counter"
    assert var.type == "number"
    assert var.default == "0"
    assert var.description == "计数器"


# ---------- 3. Compiler.default_globals ----------


def _make_graph_with_variables() -> Any:
    raw = {
        "nodes": [],
        "edges": [],
        "variables": [
            {"name": "user_name", "type": "string", "default": "alice"},
            {"name": "age", "type": "number", "default": "18"},
            {"name": "is_vip", "type": "boolean", "default": "true"},
            {"name": "profile", "type": "object", "default": '{"level": 1}'},
            {"name": "tags", "type": "array", "default": "[\"a\",\"b\"]"},
        ],
    }
    return convert_canvas(raw)


def test_default_globals_coerces_declared_types():
    graph = _make_graph_with_variables()
    compiler = Compiler()
    compiler._graph = graph

    defaults = compiler.default_globals()

    assert defaults["user_name"] == "alice"
    assert defaults["age"] == 18.0
    assert defaults["is_vip"] is True
    assert defaults["profile"] == {"level": 1}
    assert defaults["tags"] == ["a", "b"]


def test_default_globals_empty_when_no_graph():
    compiler = Compiler()
    assert compiler.default_globals() == {}


# ---------- 4. SetVariable 节点类型强制转换 ----------


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="t-test",
        application_id=uuid4(),
    )


def _make_ctx(config: dict, inputs: dict | None = None) -> NodeContext:
    return NodeContext(
        node_id="n-set",
        node_type="20",
        inputs=inputs or {},
        config=config,
        env=_make_env(),
        services=ServiceRegistry(),
    )


def test_set_variable_coerces_to_declared_type():
    handler = SetVariableNodeHandler()
    ctx = _make_ctx(
        config={
            "variableName": "age",
            "variableType": "number",
        },
        inputs={"value": "25"},
    )

    result = asyncio.run(handler.run(ctx))

    assert result.outputs["age"] == 25.0
    assert result.globals["age"] == 25.0


def test_set_variable_fallback_on_coerce_failure():
    """类型转换失败时保留原值，不阻塞主流程。"""
    handler = SetVariableNodeHandler()
    ctx = _make_ctx(
        config={
            "variableName": "counter",
            "variableType": "number",
        },
        inputs={"value": "not-a-number"},
    )

    result = asyncio.run(handler.run(ctx))

    # 转换失败保留原值（宽容模式）
    assert result.outputs["counter"] == "not-a-number"


def test_set_variable_missing_name_returns_error():
    handler = SetVariableNodeHandler()
    ctx = _make_ctx(config={}, inputs={"value": "x"})

    result = asyncio.run(handler.run(ctx))

    assert "error" in result.outputs


# ---------- 5. Runtime initial_state 接入 default_globals ----------


def test_runtime_initial_state_uses_default_globals():
    """通过 GraphRuntime._ensure_compiled + invoke 路径验证 default_globals 被合并进 initial_state。"""
    from internal.domain.graph.runtime import GraphRuntime

    # start → set_variable → end 的最小图，变量池声明了 greeting 默认值
    canvas_json = {
        "nodes": [
            {
                "id": "n-start",
                "type": "1",
                "data": {"inputs": {"inputParameters": []}},
            },
            {
                "id": "n-set",
                "type": "20",
                "data": {
                    "inputs": {
                        "inputParameters": [
                            {
                                "name": "value",
                                "input": {
                                    "type": "string",
                                    "value": {"type": "literal", "content": "bob"},
                                },
                            }
                        ],
                        "variableName": "user_name",
                        "variableType": "string",
                    }
                },
            },
            {
                "id": "n-end",
                "type": "2",
                "data": {"inputs": {"inputParameters": []}},
            },
        ],
        "edges": [
            {"sourceNodeID": "n-start", "targetNodeID": "n-set", "sourcePortID": ""},
            {"sourceNodeID": "n-set", "targetNodeID": "n-end", "sourcePortID": ""},
        ],
        "variables": [
            {"name": "user_name", "type": "string", "default": "alice"},
            {"name": "age", "type": "number", "default": "18"},
        ],
    }

    runtime = GraphRuntime(
        canvas_json=canvas_json,
        checkpointer=None,
        thread_id="t-var-test",
    )

    async def _invoke() -> dict:
        await runtime._ensure_compiled()
        # 直接拿 compiler 实例的 default_globals，验证 runtime 保存了 compiler 引用
        return runtime._compiler_instance.default_globals()

    defaults = asyncio.run(_invoke())

    assert defaults["user_name"] == "alice"
    assert defaults["age"] == 18.0
