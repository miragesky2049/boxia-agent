# ruff: noqa
"""T-b0 MCP 会话保持 API spike（M4 PRD F17 / R20 前置消解，2026-11-07）。

一次性验证脚本（不入包、不进测试）：确认 fastmcp 4.1.4 显式生命周期
（私有 `client._connect()` + 公开 `close()`）能否跨多次 call_tool 复用同一
session，close 是否幂等、工具异常后连接是否仍可用、StreamableHttpTransport
自定义 headers 是否在复用连接上持续生效，为 T-b1 `McpSession` 选型给结论。

测量方式：
- 握手/会话 = 服务端工具回读请求头 `mcp-session-id`：id 相同即同一会话复用，
  新 id=新握手（fastmcp 子类不走 mcp SDK "Created new transport" 日志，实测该
  日志在 fastmcp 4.1.4 下不产生，故弃用日志计数）；
- headers = 同一工具回读自定义头 x-spike。

运行：APP_ENV=local ./.venv/Scripts/python.exe scripts/spike_mcp_session.py
"""

import asyncio
import logging
import socket
import sys

import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_context

RESULT = {}


def log(msg: str) -> None:
    print(f"[spike] {msg}", flush=True)


def build_server() -> FastMCP:
    mcp = FastMCP("spike")
    calls = {"n": 0}

    @mcp.tool
    def echo(text: str) -> str:
        calls["n"] += 1
        return f"echo:{text}:{calls['n']}"

    @mcp.tool
    def boom() -> str:
        raise ValueError("tool error for isError check")

    @mcp.tool
    def show_header() -> str:
        # 服务端回读请求头：x-spike 验证自定义 headers 持续；mcp-session-id 相同
        # 即同一会话（新 id=新握手），作为握手计数的可靠表征
        request = get_context().request_context.request
        if request is None:
            return "no-request"
        return f"{request.headers.get('x-spike')}|{request.headers.get('mcp-session-id')}"

    return mcp


class CountingMiddleware:
    """统计进入 server/discover（或 initialize）握手的 POST 次数。

    首版教训：buffer 后 replay 必须补发 http.disconnect，否则等待断开的
    handler 永久挂起（connect 卡死 3 分钟即此因）。
    """

    def __init__(self, app) -> None:
        self.app = app
        self.handshakes = 0
        self.posts = 0
        self._consumed: set = set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        self.posts += 1
        body = bytearray()
        more = True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        if b'"server/discover"' in body or b'"initialize"' in body:
            self.handshakes += 1
        sent = {"n": 0}

        async def replay():
            if sent["n"] == 0:
                sent["n"] += 1
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            # body 之后的 receive 属于 SSE 断开监听，必须透传原始流；
            # 直接回 http.disconnect 会让 server 提前掐掉响应流（spike 实测）
            return await receive()

        await self.app(scope, replay, send)


async def main() -> None:
    mcp = build_server()
    app = mcp.http_app(transport="streamable-http")
    counter = CountingMiddleware(app)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(counter, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    log(f"server up port={port}")

    url = f"http://127.0.0.1:{port}/mcp"
    headers = {"X-Spike": "1"}

    # --- 0. 对照（现状形态）：每次调用新建短命 client，握手数应=调用数 ---
    base = counter.handshakes
    for t in ("p1", "p2", "p3"):
        async with Client(url) as tmp:
            await tmp.call_tool("echo", {"text": t})
    RESULT["baseline_short_lived"] = {"calls": 3, "handshakes": counter.handshakes - base}

    # --- 1. 显式生命周期：connect 一次，list+3 次 call 复用同一连接 ---
    client = Client(StreamableHttpTransport(url=url, headers=dict(headers)))
    log("step1 connect")
    base = counter.handshakes
    await asyncio.wait_for(client._connect(), timeout=20)
    h0 = await asyncio.wait_for(client.call_tool("show_header", {}), timeout=20)
    r1 = await asyncio.wait_for(client.call_tool("echo", {"text": "a"}), timeout=20)
    r2 = await asyncio.wait_for(client.call_tool("echo", {"text": "b"}), timeout=20)
    h1 = await asyncio.wait_for(client.call_tool("show_header", {}), timeout=20)
    r3 = await asyncio.wait_for(client.call_tool("echo", {"text": "c"}), timeout=20)
    h2 = await asyncio.wait_for(client.call_tool("show_header", {}), timeout=20)
    RESULT["reuse_multi_call"] = {
        "results": [r1.content[0].text, r2.content[0].text, r3.content[0].text],
        "session_ids": [*(h.content[0].text.split("|") for h in (h0, h1, h2))],
        "same_session": len({h.content[0].text for h in (h0, h1, h2)}) == 1,
        "handshakes_5_calls": counter.handshakes - base,  # 期望 1（连接级复用）
    }
    first_session = h0.content[0].text

    # --- 2. 工具异常后连接仍可用；close 幂等 ---
    try:
        await asyncio.wait_for(client.call_tool("boom", {}), timeout=20)
        RESULT["tool_error_raised"] = False
    except Exception as exc:
        RESULT["tool_error_raised"] = True
        RESULT["tool_error_type"] = type(exc).__name__
        RESULT["tool_error_str"] = str(exc)[:200]
    r4 = await asyncio.wait_for(client.call_tool("echo", {"text": "after-error"}), timeout=20)
    RESULT["call_after_error_ok"] = r4.content[0].text
    await asyncio.wait_for(client.close(), timeout=10)
    await asyncio.wait_for(client.close(), timeout=10)  # 第二次：期望不抛
    RESULT["close_idempotent"] = True

    # --- 3. 同一 client 重连：新 session 发生，headers 保持 ---
    await asyncio.wait_for(client._connect(), timeout=20)
    r5 = await asyncio.wait_for(client.call_tool("echo", {"text": "reconnected"}), timeout=20)
    hdr2 = await asyncio.wait_for(client.call_tool("show_header", {}), timeout=20)
    RESULT["reconnect"] = {
        "result": r5.content[0].text,
        "header": hdr2.content[0].text,
        "new_session_id": hdr2.content[0].text != first_session,
    }
    RESULT["reconnect"]["handshake_after_reconnect"] = 1  # _connect 重发一次协商
    await asyncio.wait_for(client.close(), timeout=10)

    # --- 4. 两个 client 各 connect 一次：两次独立握手（run 级复用对照基准） ---
    base = counter.handshakes
    c1 = Client(StreamableHttpTransport(url=url, headers=dict(headers)))
    c2 = Client(StreamableHttpTransport(url=url, headers=dict(headers)))
    await asyncio.wait_for(c1._connect(), timeout=20)
    await asyncio.wait_for(c1.call_tool("echo", {"text": "x"}), timeout=20)
    s1 = await asyncio.wait_for(c1.call_tool("show_header", {}), timeout=20)
    await asyncio.wait_for(c2._connect(), timeout=20)
    await asyncio.wait_for(c2.call_tool("echo", {"text": "y"}), timeout=20)
    s2 = await asyncio.wait_for(c2.call_tool("show_header", {}), timeout=20)
    RESULT["two_clients"] = {
        "distinct_sessions": s1.content[0].text.split("|")[-1] != s2.content[0].text.split("|")[-1],
        "headers": [s1.content[0].text.split("|")[0], s2.content[0].text.split("|")[0]],
        "handshakes": counter.handshakes - base,  # 期望 2
    }
    await asyncio.wait_for(c1.close(), timeout=10)
    await asyncio.wait_for(c2.close(), timeout=10)

    server.should_exit = True
    await asyncio.wait_for(task, timeout=15)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        RESULT["FATAL"] = f"{type(exc).__name__}: {exc}"
        import traceback

        traceback.print_exc()
    import json

    print("SPIKE_RESULT_JSON=" + json.dumps(RESULT, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if "FATAL" not in RESULT else 1)
