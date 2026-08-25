"""配置 OpenTelemetry TracerProvider 与 Span exporter。"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.environment_variables import (
    OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    OTEL_SERVICE_NAME,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_tracer_provider: TracerProvider | None = None


def get_tracer_provider(service_name: str = "boxia-agent") -> TracerProvider:
    """获取全局 TracerProvider（单例）。

    - 设置 OTEL_EXPORTER_OTLP_ENDPOINT 或 OTEL_EXPORTER_OTLP_TRACES_ENDPOINT 时，
      span 上报到 OTLP Collector/Jaeger（OTLPSpanExporter 内部自动拼接信号路径）
    - 否则输出到控制台（ConsoleSpanExporter），便于本地开发查看
    """
    global _tracer_provider
    if _tracer_provider is None:
        service_name = os.getenv(OTEL_SERVICE_NAME, service_name)
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if os.getenv(OTEL_EXPORTER_OTLP_ENDPOINT) or os.getenv(
            OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
        ):
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
    return _tracer_provider
