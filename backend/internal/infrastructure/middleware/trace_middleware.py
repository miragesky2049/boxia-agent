"""OpenTelemetry 链路追踪安装入口。"""

from typing import Any

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.trace import Span

from internal.infrastructure.config.settings import Settings
from internal.infrastructure.model.database import get_engine
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


def install_trace(app: FastAPI, settings: Settings) -> None:
    """启用 FastAPI 与 SQLAlchemy 自动插桩。"""
    provider = get_tracer_provider(settings.otel_service_name, settings)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        client_response_hook=_inject_traceparent_to_response,
    )
    SQLAlchemyInstrumentor().instrument(engine=get_engine(), tracer_provider=provider)
