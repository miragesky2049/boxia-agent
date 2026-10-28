"""跨网工具调用统一治理层：超时 / 重试 / 熔断 / 限流 / 连接池 / 降级。

所有 HTTP 工具调用强制经过这一层，不允许 HttpTool 裸调 httpx。
设计目标：让 LLM 主循环与 ToolNode 完全无感租户网络问题——熔断/限流/连接失败
时返回标准 observation 文本回灌 LLM，而不是把异常抛到主循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from internal.application.errors import ValidationError
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.engine.context import AgentRunContext
from internal.infrastructure.security.ssrf_guard import validate_outbound_url

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """工具执行失败：runner 捕获后作为 tool 结果回灌给 LLM，不中断主循环。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

# ---------- 全局默认配置（可被 ToolEntity.config.gateway 覆盖） ----------
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_OVERALL_TIMEOUT = 45.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_BASE = 0.5  # 0.5s → 1.0s
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_CIRCUIT_OPEN_SECONDS = 30.0
DEFAULT_RATE_LIMIT_PER_SECOND = 20
DEFAULT_RESPONSE_CLIP_BYTES = 8 * 1024  # 8KB


# ---------- 错误分类 ----------
class ToolError(Exception):
    """工具调用错误基类；is_retriable 决定是否自动重试。"""

    def __init__(self, message: str, *, is_retriable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retriable = is_retriable


class ToolTimeoutError(ToolError):
    def __init__(self, message: str = "工具调用超时") -> None:
        super().__init__(message, is_retriable=True)


class ToolConnectionError(ToolError):
    def __init__(self, message: str = "无法连接到租户工具服务") -> None:
        super().__init__(message, is_retriable=True)


class ToolAuthError(ToolError):
    def __init__(self, message: str = "工具鉴权失败") -> None:
        super().__init__(message, is_retriable=False)


class ToolRateLimitError(ToolError):
    def __init__(self, message: str = "工具被限流") -> None:
        super().__init__(message, is_retriable=True)


class ToolServerError(ToolError):
    def __init__(self, message: str = "工具服务端错误") -> None:
        super().__init__(message, is_retriable=True)


class ToolClientError(ToolError):
    def __init__(self, message: str = "工具调用参数错误") -> None:
        super().__init__(message, is_retriable=False)


# ---------- 熔断器 ----------
@dataclass
class _CircuitState:
    failure_count: int = 0
    opened_at: float = 0.0
    state: str = "closed"  # closed / open / half_open


class _CircuitBreaker:
    """按 (tenant, tool) 维度的简易熔断器：连续失败 N 次打开 30s。"""

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


# ---------- 限流器（按 tenant 维度的简单滑动窗口） ----------
class _RateLimiter:
    """按 tenant 维度的每秒固定窗口计数；超出返回 False。"""

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


# ---------- 共享 httpx 客户端 ----------
@dataclass
class _ClientPool:
    """按 base_url 分池的 httpx.AsyncClient 单例；进程内复用。"""

    clients: dict[str, httpx.AsyncClient] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get(self, base_url: str) -> httpx.AsyncClient:
        async with self._lock:
            client = self.clients.get(base_url)
            if client is not None and not client.is_closed:
                return client
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    DEFAULT_OVERALL_TIMEOUT,
                    connect=DEFAULT_CONNECT_TIMEOUT,
                    read=DEFAULT_READ_TIMEOUT,
                ),
                http2=True,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
            self.clients[base_url] = client
            return client


# ---------- 网关主体 ----------
@dataclass(frozen=True)
class GatewayConfig:
    """从 ToolEntity.config.gateway 解析出的覆盖项。"""

    timeout_seconds: float = DEFAULT_OVERALL_TIMEOUT
    retry_max: int = DEFAULT_MAX_RETRIES
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    circuit_open_seconds: float = DEFAULT_CIRCUIT_OPEN_SECONDS
    rate_limit_per_second: int = DEFAULT_RATE_LIMIT_PER_SECOND

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "GatewayConfig":
        raw = raw or {}
        return cls(
            timeout_seconds=float(raw.get("timeout_seconds") or DEFAULT_OVERALL_TIMEOUT),
            retry_max=int(raw.get("retry_max") or DEFAULT_MAX_RETRIES),
            circuit_failure_threshold=int(
                raw.get("circuit_failure_threshold") or DEFAULT_CIRCUIT_FAILURE_THRESHOLD
            ),
            circuit_open_seconds=float(
                raw.get("circuit_open_seconds") or DEFAULT_CIRCUIT_OPEN_SECONDS
            ),
            rate_limit_per_second=int(
                raw.get("rate_limit_per_second") or DEFAULT_RATE_LIMIT_PER_SECOND
            ),
        )


class ToolGateway:
    """跨网工具调用统一入口；HttpTool 必须通过 invoke_http() 调用远端。"""

    def __init__(self) -> None:
        self._pool = _ClientPool()
        self._breakers: dict[int, _CircuitBreaker] = {}
        self._limiters: dict[int, _RateLimiter] = {}

    def _get_breaker(self, cfg: GatewayConfig) -> _CircuitBreaker:
        key = hash((cfg.circuit_failure_threshold, cfg.circuit_open_seconds))
        if key not in self._breakers:
            self._breakers[key] = _CircuitBreaker(
                threshold=cfg.circuit_failure_threshold,
                open_seconds=cfg.circuit_open_seconds,
            )
        return self._breakers[key]

    def _get_limiter(self, cfg: GatewayConfig) -> _RateLimiter:
        key = hash(cfg.rate_limit_per_second)
        if key not in self._limiters:
            self._limiters[key] = _RateLimiter(cfg.rate_limit_per_second)
        return self._limiters[key]

    @staticmethod
    def _tenant_label(tenant_id: Any) -> str:
        if tenant_id is None or tenant_id == PLATFORM_TENANT_ID:
            return "platform"
        return str(tenant_id)[:8]

    async def invoke_http(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        params: dict[str, Any] | None,
        context: AgentRunContext,
        tool_name: str,
        cfg: GatewayConfig,
    ) -> str:
        """完整治理流程：熔断 → 限流 → 重试 → 错误分类 → 响应裁剪。

        熔断/限流/连接失败时返回标准 observation 文本，不抛异常给 LLM 主循环；
        4xx/业务错误抛 ToolExecutionError（不重试）。
        """
        # SSRF 防护：拒绝 loopback / 云元数据 / link-local / multicast / reserved
        try:
            validate_outbound_url(url)
        except ValidationError as exc:
            return f"工具地址不安全：{exc.message}，请告知用户检查工具配置。"

        tenant = self._tenant_label(context.tenant_id)
        breaker_key = f"{tenant}:{tool_name}"
        limiter_key = tenant

        breaker = self._get_breaker(cfg)
        limiter = self._get_limiter(cfg)

        if not await breaker.allow(breaker_key):
            logger.info("tool circuit open tool=%s tenant=%s", tool_name, tenant)
            return "工具当前不可用（服务熔断），请告知用户稍后重试或换一种方式。"

        if not await limiter.allow(limiter_key):
            logger.info("tool rate limited tenant=%s tool=%s", tenant, tool_name)
            return "工具调用过于频繁，请稍后重试。"

        # 透传业务 header（不含平台自己的 Authorization）
        request_headers = {**headers}
        request_headers.update(context.llm_headers())

        base_url = f"{url.split('/')[0]}//{url.split('/')[2]}"
        client = await self._pool.get(base_url)

        last_error: ToolError | None = None
        for attempt in range(cfg.retry_max + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    headers=request_headers,
                    json=json_body,
                    params=params,
                    timeout=cfg.timeout_seconds,
                )
                last_error = _classify_http_response(response, tool_name)
                if last_error is None:
                    await breaker.record_success(breaker_key)
                    return _clip_response(response.text)
                if not last_error.is_retriable or attempt >= cfg.retry_max:
                    break
                logger.warning(
                    "tool retriable error tool=%s attempt=%d err=%s",
                    tool_name,
                    attempt,
                    last_error.message,
                )
            except httpx.TimeoutException as exc:
                last_error = ToolTimeoutError(f"工具调用超时: {exc}")
            except httpx.ConnectError as exc:
                last_error = ToolConnectionError(f"无法连接: {exc}")
            except httpx.HTTPError as exc:
                last_error = ToolConnectionError(f"网络错误: {exc}")

            if last_error is not None and not last_error.is_retriable:
                break
            if attempt < cfg.retry_max:
                await asyncio.sleep(DEFAULT_RETRY_BACKOFF_BASE * (2**attempt))

        # 重试耗尽或不可重试
        await breaker.record_failure(breaker_key)
        assert last_error is not None
        # 连接类/超时类错误返回友好文本给 LLM；4xx/业务错误抛异常
        if isinstance(
            last_error,
            (ToolTimeoutError, ToolConnectionError, ToolServerError, ToolRateLimitError),
        ):
            return f"工具调用失败：{last_error.message}。请告知用户稍后重试或换一种方式。"
        raise ToolExecutionError(last_error.message)


def _classify_http_response(
    response: httpx.Response, tool_name: str
) -> ToolError | None:
    """按状态码分类；返回 None 表示成功。"""
    code = response.status_code
    if 200 <= code < 400:
        return None
    if code in (401, 403):
        return ToolAuthError(f"工具鉴权失败 HTTP {code}")
    if code == 429:
        return ToolRateLimitError(f"工具被限流 HTTP 429")
    if 500 <= code < 600:
        return ToolServerError(f"工具服务端错误 HTTP {code}")
    return ToolClientError(f"工具调用参数错误 HTTP {code}: {response.text[:200]}")


def _clip_response(text: str) -> str:
    """裁剪响应到 8KB，防 prompt 爆炸；尝试美化 JSON。"""
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        text = json.dumps(parsed, ensure_ascii=False)
    except (ValueError, json.JSONDecodeError):
        pass
    if len(text.encode("utf-8")) > DEFAULT_RESPONSE_CLIP_BYTES:
        return text[:DEFAULT_RESPONSE_CLIP_BYTES] + "\n...[truncated]"
    return text


# 模块级单例
_global_gateway: ToolGateway | None = None


def get_tool_gateway() -> ToolGateway:
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = ToolGateway()
    return _global_gateway
