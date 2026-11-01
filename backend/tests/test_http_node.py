"""T9: HTTP 节点扩展配置单测。

验证：
- 路径参数 :id 替换为 pathParams 对应值（URL 编码）
- queryParams 拼接到 URL params
- headers 自定义请求头
- authType=bearer 加 Authorization: Bearer xxx
- authType=basic 加 Authorization: Basic base64(user:pass)
- bodyType=json 发送 JSON body
- bodyType=form 发送 form 表单（data 而非 json）
- bodyType=none 时 GET 用 inputs 当 query，POST 用 inputs 当 json body（向后兼容）
- 服务未注册时返回 stub
"""

from __future__ import annotations

import asyncio
from base64 import b64encode
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.http import (
    HttpNodeHandler,
    _apply_path_params,
    _build_auth_headers,
    _to_kv_dict,
)


class _CapturingHttp:
    """捕获 request 调用参数，返回 fake response。"""

    def __init__(self, status: int = 200, body: str = "ok") -> None:
        self.calls: list[dict] = []
        self._status = status
        self._body = body

    async def request(self, **kwargs) -> "_CapturingHttp":
        self.calls.append(kwargs)
        return self

    @property
    def status_code(self) -> int:
        return self._status

    @property
    def text(self) -> str:
        return self._body


def _make_ctx(config: dict, *, inputs: dict | None = None,
              http: _CapturingHttp | None = None) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="t",
        application_id=uuid4(),
    )
    services = ServiceRegistry()
    if http is not None:
        services.register("http", http)
    return NodeContext(
        node_id="http_1",
        node_type=NodeType.HTTP.value,
        inputs=inputs or {},
        config=config,
        env=env,
        services=services,
    )


def test_to_kv_dict_handles_list_and_dict() -> None:
    assert _to_kv_dict([{"key": "a", "value": "1"}, {"key": "b", "value": "2"}]) == {"a": "1", "b": "2"}
    assert _to_kv_dict({"x": 1, "y": "2"}) == {"x": "1", "y": "2"}
    assert _to_kv_dict(None) == {}
    assert _to_kv_dict("not-a-list") == {}


def test_apply_path_params_replaces_and_encodes() -> None:
    url = "https://api.example.com/users/:id/posts/:slug"
    out = _apply_path_params(url, {"id": "123", "slug": "hello world"})
    assert out == "https://api.example.com/users/123/posts/hello%20world"


def test_build_auth_headers_bearer_and_basic() -> None:
    assert _build_auth_headers("bearer", "tok", "") == {"Authorization": "Bearer tok"}
    expected = "Basic " + b64encode(b"user:pass").decode("ascii")
    assert _build_auth_headers("basic", "user", "pass") == {"Authorization": expected}
    assert _build_auth_headers("none", "tok", "") == {}


def test_http_get_with_path_query_and_headers() -> None:
    http = _CapturingHttp()
    cfg = {
        "url": "https://api.example.com/users/:id",
        "method": "GET",
        "pathParams": [{"key": "id", "value": "42"}],
        "queryParams": [{"key": "foo", "value": "bar"}],
        "headers": [{"key": "X-Req-Id", "value": "abc"}],
    }
    ctx = _make_ctx(cfg, http=http)
    result = asyncio.run(HttpNodeHandler().run(ctx))
    assert result.outputs["status"] == 200
    call = http.calls[0]
    assert call["url"] == "https://api.example.com/users/42"
    assert call["params"] == {"foo": "bar"}
    assert call["headers"]["X-Req-Id"] == "abc"
    assert call["json_body"] is None


def test_http_post_json_body_with_bearer_auth() -> None:
    http = _CapturingHttp()
    cfg = {
        "url": "https://api.example.com/items",
        "method": "POST",
        "authType": "bearer",
        "authToken": "secret-token",
        "bodyType": "json",
        "bodyJson": '{"name": "boxia"}',
    }
    ctx = _make_ctx(cfg, http=http)
    result = asyncio.run(HttpNodeHandler().run(ctx))
    call = http.calls[0]
    assert call["json_body"] == {"name": "boxia"}
    assert call["headers"]["Authorization"] == "Bearer secret-token"
    assert call["headers"]["Content-Type"] == "application/json"


def test_http_post_form_body() -> None:
    http = _CapturingHttp()
    cfg = {
        "url": "https://api.example.com/login",
        "method": "POST",
        "bodyType": "form",
        "bodyForm": [{"key": "user", "value": "admin"}, {"key": "pwd", "value": "123"}],
    }
    ctx = _make_ctx(cfg, http=http)
    asyncio.run(HttpNodeHandler().run(ctx))
    call = http.calls[0]
    assert call["form_body"] == {"user": "admin", "pwd": "123"}
    assert call["json_body"] is None
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_http_backward_compat_get_uses_inputs_as_query() -> None:
    http = _CapturingHttp()
    cfg = {"url": "https://api.example.com/search", "method": "GET", "bodyType": "none"}
    ctx = _make_ctx(cfg, inputs={"q": "hello"}, http=http)
    asyncio.run(HttpNodeHandler().run(ctx))
    call = http.calls[0]
    assert call["params"] == {"q": "hello"}


def test_http_backward_compat_post_uses_inputs_as_json() -> None:
    http = _CapturingHttp()
    cfg = {"url": "https://api.example.com/echo", "method": "POST", "bodyType": "none"}
    ctx = _make_ctx(cfg, inputs={"msg": "hi"}, http=http)
    asyncio.run(HttpNodeHandler().run(ctx))
    call = http.calls[0]
    assert call["json_body"] == {"msg": "hi"}


def test_http_stub_when_service_missing() -> None:
    cfg = {"url": "https://example.com", "method": "GET"}
    ctx = _make_ctx(cfg, http=None)
    result = asyncio.run(HttpNodeHandler().run(ctx))
    assert result.outputs["status"] == 0
    assert "stub" in result.outputs["body"]
