"""工具调用治理共享组件：熔断器 / 限流器（M4-b F17.5 从 ToolGateway 抽出）。

HTTP 工具（ToolGateway）与 MCP 调用（agent_loop mcp 分支）共用同一实现，
保证"与 HTTP 工具同参口径"（阈值/开窗语义一致），按各自 key 维度隔离状态。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _CircuitState:
    failure_count: int = 0
    opened_at: float = 0.0
    state: str = "closed"  # closed / open / half_open


class CircuitBreaker:
    """按调用方自定义 key 的简易熔断器：连续失败 N 次打开 open_seconds 秒。

    状态机：closed --（连续失败达阈值或半开再失败）--> open --（冷却到期）-->
    half_open --（放行一次试探：成功回 closed / 失败回 open）。
    """

    def __init__(self, threshold: int, open_seconds: float) -> None:
        self._threshold = threshold
        self._open_seconds = open_seconds
        self._states: dict[str, _CircuitState] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            if state.state == "closed":
                return True
            if state.state == "open":
                if time.monotonic() - state.opened_at >= self._open_seconds:
                    state.state = "half_open"
                    return True
                return False
            # half_open：放行一次试探
            return True

    async def record_success(self, key: str) -> None:
        async with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failure_count = 0
            state.state = "closed"

    async def record_failure(self, key: str) -> None:
        async with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failure_count += 1
            if state.state == "half_open" or state.failure_count >= self._threshold:
                state.state = "open"
                state.opened_at = time.monotonic()


class RateLimiter:
    """按调用方自定义 key 的每秒固定窗口计数；超出返回 False。"""

    def __init__(self, per_second: int) -> None:
        self._limit = per_second
        self._window_start: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            start = self._window_start.get(key, 0.0)
            if now - start >= 1.0:
                self._window_start[key] = now
                self._counts[key] = 0
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key] <= self._limit
