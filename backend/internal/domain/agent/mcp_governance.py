"""MCP 路径治理单例（M4-b F17.5）：熔断 + 限流，与 HTTP 工具同参口径。

复用 governance 共享组件；阈值取 ToolGateway 默认常量（同参口径），
key 维度为 tenant+server（MCP server URL）。进程内单例，由 agent_loop
在 mcp 分支调用。
"""

from __future__ import annotations

from internal.domain.agent.governance import CircuitBreaker, RateLimiter
from internal.domain.agent.tool_gateway import (
    DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    DEFAULT_CIRCUIT_OPEN_SECONDS,
    DEFAULT_RATE_LIMIT_PER_SECOND,
)

_breaker: CircuitBreaker | None = None
_limiter: RateLimiter | None = None


def get_mcp_breaker() -> CircuitBreaker:
    """MCP 熔断器单例（连续失败 5 次打开 30s，与 HTTP 工具同参）。"""
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker(
            threshold=DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
            open_seconds=DEFAULT_CIRCUIT_OPEN_SECONDS,
        )
    return _breaker


def get_mcp_limiter() -> RateLimiter:
    """MCP 限流器单例（每秒 20 次，与 HTTP 工具同参）。"""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(per_second=DEFAULT_RATE_LIMIT_PER_SECOND)
    return _limiter
