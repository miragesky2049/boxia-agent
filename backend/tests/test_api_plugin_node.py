"""A10：API / 插件节点（coze type=4）单测。

覆盖：
1. 缺 pluginName 时返回 error outputs。
2. 无 tool_executor 服务时返回 stub，不阻塞开发态。
3. 有 tool_executor 时正确调用 (name, args) 并回传 output。
4. 返回文本是合法 JSON 时，额外给 parsed 字段。
5. tool_executor 抛异常时包装成 RuntimeError 抛给 Runtime 处理。
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import (
    NodeContext,
    RuntimeEnv,
    ServiceRegistry,
)
from internal.domain.graph.nodes import get_node_handler
from internal.domain.graph.nodes.api_plugin import ApiPluginNodeHandler


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="t-api",
        application_id=uuid4(),
    )


def _make_ctx(
    config: dict,
    inputs: dict | None = None,
    services: ServiceRegistry | None = None,
) -> NodeContext:
    return NodeContext(
        node_id="n-api",
        node_type=NodeType.API.value,
        inputs=inputs or {},
        config=config,
        env=_make_env(),
        services=services or ServiceRegistry(),
    )


def test_handler_registered():
    handler = get_node_handler(NodeType.API)
    assert isinstance(handler, ApiPluginNodeHandler)


def test_missing_plugin_name_returns_error():
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(config={}, inputs={"city": "北京"})

    result = asyncio.run(handler.run(ctx))

    assert "error" in result.outputs


def test_no_tool_executor_returns_stub():
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"pluginName": "weather.get"},
        inputs={"city": "北京"},
    )

    result = asyncio.run(handler.run(ctx))

    assert "plugin stub" in result.outputs["output"]
    assert result.outputs["plugin"] == "weather.get"
    assert result.outputs["args"] == {"city": "北京"}


def test_calls_tool_executor_with_name_and_args():
    captured: dict = {}

    async def fake_executor(name: str, args: dict) -> str:
        captured["name"] = name
        captured["args"] = args
        return "温度 25°C"

    services = ServiceRegistry({"tool_executor": fake_executor})
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"pluginName": "weather.get"},
        inputs={"city": "北京", "days": 3},
        services=services,
    )

    result = asyncio.run(handler.run(ctx))

    assert captured["name"] == "weather.get"
    assert captured["args"] == {"city": "北京", "days": 3}
    assert result.outputs["output"] == "温度 25°C"
    assert result.outputs["plugin"] == "weather.get"


def test_json_response_gets_parsed_field():
    async def fake_executor(name: str, args: dict) -> str:
        return '{"temp": 25, "city": "北京"}'

    services = ServiceRegistry({"tool_executor": fake_executor})
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"pluginName": "weather.get"},
        inputs={"city": "北京"},
        services=services,
    )

    result = asyncio.run(handler.run(ctx))

    assert result.outputs["parsed"] == {"temp": 25, "city": "北京"}


def test_non_json_response_no_parsed_field():
    async def fake_executor(name: str, args: dict) -> str:
        return "plain text, not json"

    services = ServiceRegistry({"tool_executor": fake_executor})
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"pluginName": "weather.get"},
        inputs={},
        services=services,
    )

    result = asyncio.run(handler.run(ctx))

    assert "parsed" not in result.outputs
    assert result.outputs["output"] == "plain text, not json"


def test_tool_executor_exception_wrapped_as_runtime_error():
    async def broken_executor(name: str, args: dict) -> str:
        raise ConnectionError("downstream unreachable")

    services = ServiceRegistry({"tool_executor": broken_executor})
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"pluginName": "weather.get"},
        inputs={"city": "北京"},
        services=services,
    )

    with pytest.raises(RuntimeError, match="插件 weather.get 调用失败"):
        asyncio.run(handler.run(ctx))


def test_accepts_tool_name_alias():
    """config 兼容 toolName / name 两种 alias。"""
    captured: dict = {}

    async def fake_executor(name: str, args: dict) -> str:
        captured["name"] = name
        return "ok"

    services = ServiceRegistry({"tool_executor": fake_executor})
    handler = ApiPluginNodeHandler()
    ctx = _make_ctx(
        config={"toolName": "search.web"},
        inputs={"q": "boxia"},
        services=services,
    )

    result = asyncio.run(handler.run(ctx))

    assert captured["name"] == "search.web"
    assert result.outputs["output"] == "ok"
