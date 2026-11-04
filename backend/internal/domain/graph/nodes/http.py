"""HTTP 请求节点（coze type=45）。

config 约定：
- url / method / timeoutMs
- pathParams: [{key, value}] — URL 中 :param 形式的路径参数
- queryParams: [{key, value}] — 拼接到 URL ? 后的查询参数
- headers: [{key, value}] — 自定义 HTTP 请求头
- authType: none/bearer/basic
- authToken: bearer token 或 basic 用户名
- authSecret: basic 密码
- bodyType: none/json/form
- bodyJson: JSON Body 对象字符串
- bodyForm: [{key, value}] — form 表单键值对
"""

from __future__ import annotations

import json
import logging
import re
from base64 import b64encode
from typing import Any
from urllib.parse import quote

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)

_PATH_PARAM_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")


def _to_kv_dict(raw: Any) -> dict[str, str]:
    """把 [{key, value}] 数组 / dict 转成 dict[str, str]。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        result: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("name") or item.get("field")
            value = item.get("value")
            if key is None:
                continue
            result[str(key)] = "" if value is None else str(value)
        return result
    return {}


def _apply_path_params(url: str, path_params: dict[str, str]) -> str:
    """把 URL 中的 :param 替换为 path_params 里对应的值（URL 编码）。"""
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in path_params:
            return match.group(0)
        return quote(path_params[name], safe="")
    return _PATH_PARAM_RE.sub(_replace, url)


def _build_auth_headers(auth_type: str, token: str, secret: str) -> dict[str, str]:
    """按 authType 构造认证头。"""
    if auth_type == "bearer" and token:
        return {"Authorization": f"Bearer {token}"}
    if auth_type == "basic" and token:
        raw = f"{token}:{secret or ''}".encode("utf-8")
        return {"Authorization": f"Basic {b64encode(raw).decode('ascii')}"}
    return {}


def _parse_json_body(raw: Any) -> Any:
    """把 bodyJson 字符串解析成对象；解析失败返回原始字符串。"""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return raw


class HttpNodeHandler(NodeHandler):
    type_name = NodeType.HTTP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        method = str(config.get("method") or "GET").upper()
        timeout_s = float(config.get("timeoutMs", 30000) or 30000) / 1000.0

        # 1. 路径参数替换
        path_params = _to_kv_dict(config.get("pathParams"))
        url = _apply_path_params(str(config.get("url") or ""), path_params)

        # 2. query params
        query_params = _to_kv_dict(config.get("queryParams"))

        # 3. headers + auth
        headers = _to_kv_dict(config.get("headers"))
        auth_headers = _build_auth_headers(
            str(config.get("authType") or "none"),
            str(config.get("authToken") or ""),
            str(config.get("authSecret") or ""),
        )
        headers.update(auth_headers)

        # 4. body
        body_type = str(config.get("bodyType") or "none")
        json_body: Any = None
        form_body: dict[str, str] | None = None
        if body_type == "json":
            json_body = _parse_json_body(config.get("bodyJson"))
            # 兼容旧逻辑：未配置 bodyJson 时用 inputs 兜底
            if json_body is None and ctx.inputs:
                json_body = ctx.inputs
            headers.setdefault("Content-Type", "application/json")
        elif body_type == "form":
            form_body = _to_kv_dict(config.get("bodyForm"))
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            # bodyType=none：GET 用 inputs 当 query；其他方法用 inputs 当 json body（向后兼容）
            if method == "GET":
                if not query_params and ctx.inputs:
                    query_params = {**query_params, **{k: str(v) for k, v in ctx.inputs.items()}}
            else:
                if json_body is None and ctx.inputs:
                    json_body = ctx.inputs

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
                params=query_params or None,
                json_body=json_body,
                form_body=form_body,
                timeout=timeout_s,
                headers=headers or None,
            )
        except Exception as exc:
            logger.exception("HTTP 调用失败: %s %s", method, url)
            raise RuntimeError(f"HTTP 请求失败: {exc}") from exc

        status_code = int(getattr(resp, "status_code", 0))
        resp_body = getattr(resp, "text", str(resp))

        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}: {resp_body[:200]}")

        return NodeResult(outputs={
            "status": status_code,
            "body": resp_body[:8192],
        })


register_node_handler(HttpNodeHandler())
