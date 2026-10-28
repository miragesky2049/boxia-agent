"""SSE 响应工具：统一事件格式与 headers。"""

from __future__ import annotations

import json
from typing import Any

# SSE 响应头：长连接、不缓冲、不缓存
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(event: str, data: dict[str, Any]) -> str:
    """把一个事件格式化为 SSE 帧。

    输出形如：
        event: run_start
        data: {"run_id":"..."}

    末尾留一个空行作为帧分隔。
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
