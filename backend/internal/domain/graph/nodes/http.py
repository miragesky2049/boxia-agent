"""HTTP 请求节点（coze type=45）。

config 约定：
- url / method / headers / params / body / timeoutMs
"""

from __future__ import annotations

import logging

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class HttpNodeHandler(NodeHandler):
    type_name = NodeType.HTTP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        url = str(config.get("url") or "")
        method = str(config.get("method") or "GET").upper()
        timeout_s = float(config.get("timeoutMs", 30000) or 30000) / 1000.0

        # inputs 是求值后的参数，作为 query / body
        params = ctx.inputs if method == "GET" else None
        body = None if method == "GET" else ctx.inputs

        if not ctx.services.has("http"):
            return NodeResult(outputs={
                "status": 0,
                "body": f"[HTTP stub] {method} {url}",
            })

        http_service = ctx.services.get("http")
        try:
            resp = await http_service.request(
                method=method,
                url=url,
                params=params,
                json_body=body,
                timeout=timeout_s,
            )
        except Exception as exc:
            # 抛异常让 Runtime 按 ErrorPolicy 处理
            logger.exception("HTTP 调用失败: %s %s", method, url)
            raise RuntimeError(f"HTTP 请求失败: {exc}") from exc

        status_code = int(getattr(resp, "status_code", 0))
        resp_body = getattr(resp, "text", str(resp))

        # 4xx/5xx 也算失败，抛异常让 Runtime 处理
        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}: {resp_body[:200]}")

        return NodeResult(outputs={
            "status": status_code,
            "body": resp_body[:8192],
        })


register_node_handler(HttpNodeHandler())
