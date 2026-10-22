"""配置 OpenTelemetry TracerProvider 与 Span exporter。"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from internal.infrastructure.config.settings import Settings, get_settings

logger = logging.getLogger("boxia.trace")
_tracer_provider: TracerProvider | None = None


def get_tracer_provider(
    service_name: str | None = None, settings: Settings | None = None
) -> TracerProvider:
    """获取全局 TracerProvider（单例）。

    生产环境只允许 OTLP 导出；未配置端点时不导出 span，避免控制台泄露数据。
    """
    global _tracer_provider
    if _tracer_provider is not None:
        return _tracer_provider

    settings = settings or get_settings()
    service = service_name or settings.otel_service_name
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": service, "service.version": settings.app_version}
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_ratio)),
    )
    if settings.otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    elif not settings.is_production:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        logger.warning("OTLP endpoint 未配置，生产环境不导出追踪数据")

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider
