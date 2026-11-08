"""tool_gateway 单元测试：熔断 / 限流 / 错误分类 / 响应裁剪 / 重试。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.domain.agent.governance import CircuitBreaker as _CircuitBreaker
from internal.domain.agent.governance import RateLimiter as _RateLimiter
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.agent.tool_gateway import (
    DEFAULT_RESPONSE_CLIP_BYTES,
    GatewayConfig,
    ToolClientError,
    ToolGateway,
    ToolServerError,
    _classify_http_response,
    _clip_response,
)
from internal.domain.agent.tools import ToolExecutionError
from internal.domain.constants import PLATFORM_TENANT_ID


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _ctx(tenant_id: Any = PLATFORM_TENANT_ID) -> AgentRunContext:
    return AgentRunContext(
        agent_id="test",
        tenant_id=tenant_id,
        user_id=None,
        conversation_id="test",
    )


# ---------- 熔断器 ----------
def test_circuit_breaker_opens_after_threshold() -> None:
    """连续失败达到阈值后熔断器打开，拒绝放行。"""
    breaker = _CircuitBreaker(threshold=3, open_seconds=30.0)
    key = "t:tool"

    for _ in range(2):
        _run(breaker.record_failure(key))
        assert _run(breaker.allow(key)) is True

    # 第三次失败后应打开
    _run(breaker.record_failure(key))
    assert _run(breaker.allow(key)) is False


def test_circuit_breaker_resets_on_success() -> None:
    """half_open 状态下成功调用应重置熔断器。"""
    breaker = _CircuitBreaker(threshold=2, open_seconds=30.0)
    key = "t:tool"

    _run(breaker.record_failure(key))
    _run(breaker.record_failure(key))
    # 达到阈值后 open
    assert _run(breaker.allow(key)) is False

    # 手动模拟 half_open（不依赖真实时间等待）
    breaker._states[key].state = "half_open"  # noqa: SLF001
    assert _run(breaker.allow(key)) is True

    _run(breaker.record_success(key))
    assert _run(breaker.allow(key)) is True
    assert breaker._states[key].state == "closed"  # noqa: SLF001


# ---------- 限流器 ----------
def test_rate_limiter_blocks_after_limit() -> None:
    """超过每秒限额后拒绝放行。"""
    limiter = _RateLimiter(per_second=3)
    key = "tenant"

    assert _run(limiter.allow(key)) is True
    assert _run(limiter.allow(key)) is True
    assert _run(limiter.allow(key)) is True
    assert _run(limiter.allow(key)) is False


# ---------- 错误分类 ----------
def test_classify_http_response_success() -> None:
    assert _classify_http_response(MagicMock(status_code=200), "tool") is None
    assert _classify_http_response(MagicMock(status_code=204), "tool") is None


def test_classify_http_response_client_error() -> None:
    response = MagicMock(status_code=400, text="bad request")
    err = _classify_http_response(response, "tool")
    assert isinstance(err, ToolClientError)
    assert err.is_retriable is False


def test_classify_http_response_server_error() -> None:
    response = MagicMock(status_code=503, text="")
    err = _classify_http_response(response, "tool")
    assert isinstance(err, ToolServerError)
    assert err.is_retriable is True


# ---------- 响应裁剪 ----------
def test_clip_response_truncates_long_text() -> None:
    long_text = "x" * (DEFAULT_RESPONSE_CLIP_BYTES + 100)
    clipped = _clip_response(long_text)
    assert len(clipped.encode("utf-8")) <= DEFAULT_RESPONSE_CLIP_BYTES + 20
    assert "truncated" in clipped


def test_clip_response_pretty_prints_json() -> None:
    raw = '{"a":1,"b":2}'
    result = _clip_response(raw)
    assert " " in result  # 美化后应有空格


# ---------- gateway 端到端（mock client） ----------
def _make_gateway_with_mock_client(mock_client: AsyncMock) -> ToolGateway:
    gateway = ToolGateway()
    gateway._pool.get = AsyncMock(return_value=mock_client)  # type: ignore[method-assign]
    return gateway


def test_invoke_http_circuit_open_returns_degraded_text() -> None:
    """熔断器打开时直接返回降级文本，不发请求。"""
    gateway = _make_gateway_with_mock_client(AsyncMock())
    cfg = GatewayConfig(circuit_failure_threshold=1, circuit_open_seconds=30.0)

    # 先让它失败一次打开熔断
    _run(gateway._get_breaker(cfg).record_failure("platform:http_tool"))

    result = _run(
        gateway.invoke_http(
            method="GET",
            url="http://example.com/api",
            headers={},
            json_body=None,
            params={},
            context=_ctx(),
            tool_name="http_tool",
            cfg=cfg,
        )
    )
    assert "熔断" in result
    gateway._pool.get.assert_not_called()  # type: ignore[attr-defined]


def test_invoke_http_5xx_retries_then_raises() -> None:
    """5xx 时自动重试，重试耗尽后返回降级文本（不抛异常给 LLM）。"""
    mock_response = MagicMock(status_code=503, text="")
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)

    gateway = _make_gateway_with_mock_client(mock_client)
    cfg = GatewayConfig(retry_max=1)

    result = _run(
        gateway.invoke_http(
            method="GET",
            url="http://example.com/api",
            headers={},
            json_body=None,
            params={},
            context=_ctx(),
            tool_name="flaky_tool",
            cfg=cfg,
        )
    )
    assert "工具服务端错误" in result or "失败" in result
    assert mock_client.request.call_count == 2  # 初始 + 1 次重试


def test_invoke_http_4xx_raises_tool_execution_error() -> None:
    """4xx 不重试，抛 ToolExecutionError 回灌 LLM。"""
    mock_response = MagicMock(status_code=400, text="bad params")
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)

    gateway = _make_gateway_with_mock_client(mock_client)
    cfg = GatewayConfig(retry_max=2)

    with pytest.raises(ToolExecutionError):
        _run(
            gateway.invoke_http(
                method="GET",
                url="http://example.com/api",
                headers={},
                json_body=None,
                params={},
                context=_ctx(),
                tool_name="bad_tool",
                cfg=cfg,
            )
        )
    assert mock_client.request.call_count == 1  # 不重试


def test_invoke_http_success_returns_clip_text() -> None:
    """成功响应：JSON 美化 + 裁剪。"""
    mock_response = MagicMock(status_code=200, text='{"hello":"world"}')
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)

    gateway = _make_gateway_with_mock_client(mock_client)
    cfg = GatewayConfig()

    result = _run(
        gateway.invoke_http(
            method="POST",
            url="http://example.com/api",
            headers={},
            json_body={"q": "x"},
            params=None,
            context=_ctx(),
            tool_name="ok_tool",
            cfg=cfg,
        )
    )
    assert "hello" in result
    mock_client.request.assert_awaited_once()
