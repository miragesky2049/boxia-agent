"""从 OpenTelemetry 当前 span 读取 trace 上下文视图。"""

from dataclasses import dataclass

from opentelemetry import trace


def _format_id(value: int, width: int) -> str:
    """把 OTel 的 int id 格式化为固定宽度小写 hex。"""
    return f"{value:0{width}x}" if value else ""


@dataclass(frozen=True)
class TraceContext:
    """当前请求的 trace 信息（从 OTel 活跃 span 读取的只读视图）。"""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    sampled: bool = True


def get_trace_context() -> TraceContext | None:
    """读取当前请求的 OTel span 上下文，无活跃 span 时返回 None。"""
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return None

    parent_span_id = None
    parent = getattr(span, "parent", None)
    if parent is not None:
        parent_span_id = _format_id(parent.span_id, 16)

    return TraceContext(
        trace_id=_format_id(span_context.trace_id, 32),
        span_id=_format_id(span_context.span_id, 16),
        parent_span_id=parent_span_id,
        sampled=span_context.trace_flags.sampled,
    )
