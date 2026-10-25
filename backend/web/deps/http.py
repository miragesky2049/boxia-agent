"""HTTP 请求元数据提取。"""

from fastapi import Request


def client_meta(request: Request) -> tuple[str | None, str | None]:
    """返回客户端 IP 与截断后的 User-Agent，用于审计。"""
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent
