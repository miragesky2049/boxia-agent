"""HTTP 节点服务：基于 httpx.AsyncClient 的轻量 HTTP 调用。

domain/graph/nodes/http.py 期望：
    await http_service.request(method, url, params, json_body, form_body, headers, timeout) -> {status_code, text}
"""

from __future__ import annotations

from typing import Any

import httpx


class HttpService:
    """共享一个 httpx.AsyncClient，节点调用时只传请求参数。"""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None

    async def request(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        form_body: dict[str, str] | None = None,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "params": params,
            "timeout": timeout,
            "headers": headers,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        if form_body is not None:
            kwargs["data"] = form_body
        return await self._client.request(**kwargs)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
