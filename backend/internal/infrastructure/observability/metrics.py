"""Prometheus 业务指标与 HTTP 指标装配。"""

import time

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.pool import QueuePool
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from internal.domain.agent.mcp_observer import McpCallRecord, configure_mcp_observer
from internal.domain.llm.observer import LlmCallRecord, configure_llm_observer
from internal.infrastructure.model.database import get_engine

LOGIN_SUCCESS = Counter("boxia_login_success_total", "登录成功次数")
LOGIN_FAILURE = Counter("boxia_login_failure_total", "登录失败次数", ["reason"])
REFRESH_FAILURE = Counter("boxia_refresh_failure_total", "刷新令牌失败次数", ["reason"])
AUDIT_WRITE_FAILURE = Counter("boxia_audit_write_failure_total", "审计写入失败次数")

HTTP_REQUESTS = Counter(
    "boxia_http_requests_total",
    "HTTP 请求数",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "boxia_http_request_duration_seconds",
    "HTTP 请求耗时",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# LLM 调用指标：tenant 用短码（platform = 0000...），避免 UUID 爆炸标签
LLM_DURATION = Histogram(
    "boxia_llm_request_duration_seconds",
    "LLM /chat/completions 调用耗时",
    ["tenant", "model", "status"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)
LLM_TOKENS = Counter(
    "boxia_llm_tokens_total",
    "LLM token 用量",
    ["tenant", "model", "type"],
)

# 工具调用指标
TOOL_DURATION = Histogram(
    "boxia_tool_invoke_duration_seconds",
    "工具调用耗时",
    ["tenant", "tool", "status"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
TOOL_CALLS = Counter(
    "boxia_tool_invoke_total",
    "工具调用次数",
    ["tenant", "tool", "status"],
)

# Agent 运行轮次（function calling 迭代数）
AGENT_ITERATIONS = Histogram(
    "boxia_agent_run_iterations",
    "单次 agent 运行的 LLM 迭代数",
    ["tenant"],
    buckets=(1, 2, 3, 5, 8, 12),
)

# MCP 会话与调用指标（M4-b F17.6）：server 标签基数受应用配置约束（每应用 ≤5 server）
MCP_HANDSHAKES = Counter(
    "boxia_mcp_handshake_total",
    "MCP 新建连接协议握手次数",
    ["server"],
)
MCP_SESSION_REUSE = Counter(
    "boxia_mcp_session_reuse_total",
    "MCP 会话池命中省去握手的次数",
    ["server"],
)
MCP_CALL_DURATION = Histogram(
    "boxia_mcp_call_duration_seconds",
    "MCP 工具调用端到端耗时（含建连与治理检查）",
    ["tenant", "server", "tool", "status"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
# 会话池水位：进程级单值（多 worker 下为各自进程视角，R13 粘性部署前提）
MCP_POOL_SIZE = Gauge(
    "boxia_mcp_pool_size",
    "MCP 会话池当前会话数",
)


def _pool_metric(getter: str) -> int:
    """仅对队列连接池采集指标（NullPool 等无此能力）。"""
    pool = get_engine().pool
    if not isinstance(pool, QueuePool):
        return 0
    return int(getattr(pool, getter)())


_DB_POOL_CHECKED_OUT = Gauge("boxia_db_pool_checked_out", "数据库连接池已借出连接数")
_DB_POOL_CHECKED_OUT.set_function(lambda: _pool_metric("checkedout"))
_DB_POOL_SIZE = Gauge("boxia_db_pool_size", "数据库连接池当前连接数")
_DB_POOL_SIZE.set_function(lambda: _pool_metric("size"))

_SKIP_PREFIXES = ("/health", "/metrics")


class MetricsMiddleware:
    """记录 HTTP 请求量与耗时；路由使用模板路径避免标签爆炸。"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        started = time.perf_counter()
        status = 500

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            HTTP_REQUESTS.labels(method=method, route=route_path, status=str(status)).inc()
            HTTP_DURATION.labels(method=method, route=route_path).observe(
                time.perf_counter() - started
            )


class PrometheusLlmCallObserver:
    """把 LLM 调用汇总记入 Prometheus（实现 domain 的 LlmCallObserver 端口）。"""

    def observe(self, record: LlmCallRecord) -> None:
        """记录耗时；tokens 为 None 表示失败路径，不写 0 值序列。"""
        LLM_DURATION.labels(tenant=record.tenant, model=record.model, status=record.status).observe(
            record.duration_seconds
        )
        if record.prompt_tokens is not None:
            LLM_TOKENS.labels(tenant=record.tenant, model=record.model, type="prompt").inc(
                record.prompt_tokens
            )
        if record.completion_tokens is not None:
            LLM_TOKENS.labels(tenant=record.tenant, model=record.model, type="completion").inc(
                record.completion_tokens
            )


class PrometheusMcpObserver:
    """把 MCP 握手/复用/调用汇总/池水位记入 Prometheus（实现 domain 的 McpObserver 端口）。"""

    def on_handshake(self, server: str) -> None:
        MCP_HANDSHAKES.labels(server=server).inc()

    def on_reuse(self, server: str) -> None:
        MCP_SESSION_REUSE.labels(server=server).inc()

    def observe_call(self, record: McpCallRecord) -> None:
        MCP_CALL_DURATION.labels(
            tenant=record.tenant, server=record.server, tool=record.tool, status=record.status
        ).observe(record.duration_seconds)

    def set_pool_size(self, size: int) -> None:
        MCP_POOL_SIZE.set(size)


# 本模块被导入（= 应用装配了 Prometheus）时注册观测实现；
# 未导入的进程（纯脚本/单测）走 domain 默认 no-op，行为与原 client 直连指标等价。
configure_llm_observer(PrometheusLlmCallObserver())
configure_mcp_observer(PrometheusMcpObserver())


def setup_metrics(app: FastAPI) -> None:
    """安装 HTTP 指标中间件并暴露 /metrics。"""
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    def metrics(_: Request) -> Response:
        """Prometheus 文本格式指标。"""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
