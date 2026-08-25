"""日志链路关联：基于 OpenTelemetry LoggingInstrumentor 自动注入 trace 字段。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from opentelemetry.instrumentation.logging import LoggingInstrumentor

DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s"
)


@dataclass(frozen=True)
class LoggingConfig:
    """日志配置对象，作为依赖注入来源。

    通过环境变量 LOG_LEVEL / LOG_FORMAT / LOG_TRACE_CORRELATION 覆盖。
    """

    level: int = logging.INFO
    log_format: str = DEFAULT_LOG_FORMAT
    trace_correlation: bool = True

    @classmethod
    def from_env(cls) -> LoggingConfig:
        """从环境变量构建配置，未设置时使用默认值。"""
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        return cls(
            level=getattr(logging, level_name, logging.INFO),
            log_format=os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT),
            trace_correlation=os.getenv("LOG_TRACE_CORRELATION", "true").lower()
            != "false",
        )


def setup_logging(config: LoggingConfig | None = None) -> None:
    """按注入的配置启用 OTel 日志关联并配置 root logger。

    配置由调用方注入（默认 LoggingConfig()），生产环境可用
    LoggingConfig.from_env() 从环境变量加载。在应用 lifespan 中调用，
    以覆盖 uvicorn 对 root logger 的默认配置。
    """
    config = config or LoggingConfig()

    if config.trace_correlation:
        LoggingInstrumentor().instrument(
            set_logging_format=False, inject_trace_context=True
        )

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(config.log_format))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(config.level)
    root.propagate = False
