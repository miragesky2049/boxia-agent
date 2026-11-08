# ruff: noqa
"""M4-b 真机冒烟用 MCP server（一次性脚本，不入包）。

绑定 0.0.0.0，用局域网 IP 访问以绕开 SSRF 对 loopback 的执行期拦截；
中间件把每次 POST 的 JSON-RPC 方法名打到 stdout，用于核对验收 5：
"一个 run 内 3 次工具调用 = 1 次握手（server/discover 或 initialize）"。

运行：APP_ENV=local ./.venv/Scripts/python.exe scripts/smoke_mcp_server.py [port]
"""

import asyncio
import json
import sys

import uvicorn
from fastmcp import FastMCP

mcp = FastMCP("smoke-m4b")


@mcp.tool
def lookup_city(query: str) -> str:
    """查询城市天气（冒烟桩数据）。"""
    table = {"北京": "晴 12℃", "上海": "多云 18℃", "广州": "小雨 24℃"}
    return table.get(query.strip(), f"{query}：暂无数据")


@mcp.tool
def add_two(a: int, b: int) -> dict:
    """两数相加（结构化输出冒烟）。"""
    return {"sum": a + b}


class LoggingMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        more = True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        try:
            payload = json.loads(body.decode("utf-8", "ignore") or "{}")
        except json.JSONDecodeError:
            payload = {}
        method = payload.get("method", "?") if isinstance(payload, dict) else "?"
        print(f"[mcp-requests] POST method={method}", flush=True)
        sent = {"n": 0}

        async def replay():
            if sent["n"] == 0:
                sent["n"] += 1
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    app = mcp.http_app(transport="streamable-http")
    wrapped = LoggingMiddleware(app)
    config = uvicorn.Config(wrapped, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)
    print(f"[smoke-mcp] listening 0.0.0.0:{port} path=/mcp", flush=True)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
