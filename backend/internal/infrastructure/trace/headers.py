"""下游透传：使用 OTel Propagator 按 W3C Trace Context 注入 header。"""

from opentelemetry import propagate

TRACEPARENT_HEADER = "traceparent"


def trace_headers() -> dict[str, str]:
    """调用下游服务时需要透传的 trace header，无活跃 span 时返回空 dict。

    默认使用全局 Propagator（W3CTraceContextPropagator），从当前 context 注入 traceparent。
    """
    headers: dict[str, str] = {}
    propagate.inject(headers.__setitem__)
    return headers
