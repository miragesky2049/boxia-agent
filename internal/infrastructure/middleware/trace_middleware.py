"""OpenTelemetry 链路追踪安装入口（按项目分层置于 internal/infrastructure/middleware）。"""
from typing import Any

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import Span

from internal.infrastructure.trace.exporter import get_tracer_provider


def _inject_traceparent_to_response(span: Span, _scope: dict, message: dict[str, Any]) -> None:
    """把 server span 的 traceparent 写回响应头，供调用方延续链路。"""
    headers = message.get("headers")
    if headers is None:
        return
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return
    flags = "01" if ctx.trace_flags.sampled else "00"
    traceparent = f"00-{format(ctx.trace_id, '032x')}-{format(ctx.span_id, '016x')}-{flags}"
    headers.append((b"traceparent", traceparent.encode()))


def install_trace(app: FastAPI, service_name: str = "boxia-agent") -> None:
    """为 FastAPI 应用启用 OTel 自动插桩。

    FastAPIInstrumentor 自动为应用添加中间件：请求入口创建 server span、
    按 W3C Trace Context 从请求头提取 traceparent 并延续链路、响应头写回
    traceparent，上下文随请求自动传播。
    """
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=get_tracer_provider(service_name),
        client_response_hook=_inject_traceparent_to_response,
    )
