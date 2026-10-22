"""通过 FastAPI Depends 暴露当前请求的 trace 上下文（基于 OpenTelemetry）。"""

from typing import Annotated

from fastapi import Depends

from .context import TraceContext, get_trace_context


def get_trace() -> TraceContext:
    """依赖函数：返回当前请求的 trace 上下文，无活跃 span 时返回空串兜底。"""
    ctx = get_trace_context()
    if ctx is None:
        return TraceContext(trace_id="", span_id="", parent_span_id=None)
    return ctx


TraceDep = Annotated[TraceContext, Depends(get_trace)]
