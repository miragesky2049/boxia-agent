"""结构化日志配置：开发可读、生产 JSON，并注入 request/trace 字段。"""

import logging

from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from pythonjsonlogger.json import JsonFormatter

from internal.infrastructure.config.settings import Settings
from internal.infrastructure.observability.context import get_request_id, get_user_id

_CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[request_id=%(request_id)s trace_id=%(trace_id)s span_id=%(span_id)s] %(message)s"
)
_JSON_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(trace_id)s %(span_id)s "
    "%(method)s %(path)s %(status)s %(duration_ms)s %(client_ip)s %(user_id)s"
)


class RequestContextFilter(logging.Filter):
    """为日志记录补充请求、链路与访问上下文字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else "-"
        record.span_id = format(context.span_id, "016x") if context.is_valid else "-"
        record.method = getattr(record, "method", "-")
        record.path = getattr(record, "path", "-")
        record.status = getattr(record, "status", "-")
        record.duration_ms = getattr(record, "duration_ms", "-")
        record.client_ip = getattr(record, "client_ip", "-")
        record.user_id = getattr(record, "user_id", None) or get_user_id() or "-"
        return True


def setup_logging(settings: Settings) -> None:
    """初始化根日志：统一格式、关闭 uvicorn access log 重复输出。"""
    LoggingInstrumentor().instrument(set_logging_format=False, inject_trace_context=True)

    if settings.effective_log_json:
        formatter: logging.Formatter = JsonFormatter(
            _JSON_FORMAT,
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    else:
        formatter = logging.Formatter(_CONSOLE_FORMAT)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root.propagate = False

    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
