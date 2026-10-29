"""内置节点：start / llm / end / branch / tool / template / http。"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, Awaitable, Callable
from uuid import UUID

from internal.engine.llm import LLMClient
from internal.engine.graph.registry import NodePlugin, PortSpec, register_node

logger = logging.getLogger(__name__)

# 运行时模型解析器：由 GraphRunner 在 invoke 前注入（asyncio contextvar）
# 节点无需感知会话，只通过此上下文拿到 LLMClient
ModelResolverCtx: ContextVar[Any] = ContextVar("model_resolver", default=None)

# 运行时子图加载器：由 GraphRunner 注入，签名 (application_id: str) -> dict（返回 graph JSON）
# 节点通过此上下文递归加载并执行目标 application 的 graph
SubgraphLoaderCtx: ContextVar[Any] = ContextVar("subgraph_loader", default=None)

# 运行时 tool 资源解析器：由 GraphRunner 注入，签名 (resource_id: str) -> dict | None
# 返回 tool 的 config（含 endpoint / method / params_schema），无权访问或不存在时返回 None
ToolResolverCtx: ContextVar[Any] = ContextVar("tool_resolver", default=None)

# 当前租户 ID：由 GraphRunner 在 invoke 前注入，tool/http 节点构造 AgentRunContext 用
TenantIdCtx: ContextVar[Any] = ContextVar("tenant_id", default=None)

# 运行时 RetrievalService：由 GraphRunner 注入，retrieval 节点调用向量检索
RetrievalServiceCtx: ContextVar[Any] = ContextVar("retrieval_service", default=None)

# 知识库资源解析器：由 GraphRunner 注入，签名 (resource_id: str) -> list[UUID] | None
# 把 knowledge 资源 id 解析为底层 document_ids，无权访问或不存在返回 None
KnowledgeResolverCtx: ContextVar[Any] = ContextVar("knowledge_resolver", default=None)


# ========== 通用重试辅助 ==========
async def _run_with_retry(
    action: Callable[[], Awaitable[dict[str, Any]]],
    *,
    retry_enabled: bool,
    max_retries: int,
    node_label: str,
) -> dict[str, Any]:
    """节点级失败重试：工作流编排平台通用的失败重试语义。

    - action 返回的 dict 中 error 字段非空即视为失败
    - action 可额外返回 retryable: bool，显式声明该错误是否值得重试
      （缺省 True；HTTP 4xx / LLM 4xx 这类业务错误应标 False，避免无意义重试）
    - 指数退避：第 n 次重试等待 (2 ** n) 秒（1s, 2s, 4s…）
    - retry_enabled=False 时直接执行一次
    """
    if not retry_enabled:
        return await action()

    attempts = max(1, int(max_retries) + 1)
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        result = await action()
        error = result.get("error")
        if not error:
            return result
        last_error = str(error)
        retryable = result.get("retryable", True)
        if not retryable or attempt >= attempts:
            break
        backoff = 2 ** (attempt - 1)
        logger.warning(
            "%s 节点第 %d 次失败，将在 %ds 后重试：%s",
            node_label,
            attempt,
            backoff,
            last_error,
        )
        await asyncio.sleep(backoff)
    return result


# ========== start ==========
def _start_node_build(config: dict[str, Any]):
    async def start_fn(state: dict) -> dict:
        return {"input": state.get("input", {})}

    return start_fn


# ========== llm ==========
def _llm_node_build(node_config: dict[str, Any]):
    """llm 节点：调用模型网关。

    LLMClient 通过 ModelResolverCtx 注入，节点工厂闭包捕获 node_config。
    LLM 节点通用语义：
      - system_prompt / user_prompt 独立配置，user_prompt 支持 {{#input.xxx#}} 占位符
      - response_format_json=True 时透传 OpenAI response_format={"type": "json_object"}
      - retry_enabled=True 时节点级失败重试（指数退避）
    """
    system_prompt: str = node_config.get("system_prompt", "")
    user_prompt_template: str = node_config.get("user_prompt", "")
    model_id: str = node_config.get("model_id", "")
    temperature: float = node_config.get("temperature", 0.7)
    max_tokens: int | None = node_config.get("max_tokens")
    response_json: bool = bool(node_config.get("response_format_json", False))
    retry_enabled: bool = bool(node_config.get("retry_enabled", False))
    max_retries: int = int(node_config.get("max_retries", 3) or 3)
    # OpenAI 标准采样参数：None 表示不配置，由网关默认值决定
    top_p: float | None = node_config.get("top_p")
    presence_penalty: float | None = node_config.get("presence_penalty")
    frequency_penalty: float | None = node_config.get("frequency_penalty")

    async def _do_llm(state: dict) -> dict:
        resolver = ModelResolverCtx.get()
        user_input = state.get("input", {})

        # user_prompt 优先：未配置时回退到 input.message/query
        if user_prompt_template:
            user_message = _resolve_template(user_prompt_template, state)
        else:
            user_message = user_input.get("message") or user_input.get("query") or str(user_input)

        if resolver is None or not model_id:
            return {
                "output": {
                    "content": f"[LLM stub] model={model_id} input={str(user_message)[:80]}",
                    "model": model_id,
                },
                "error": None,
            }

        client: LLMClient = resolver(model_id)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(user_message)})

        response_format = {"type": "json_object"} if response_json else None
        try:
            resp = await client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                top_p=top_p,
                presence_penalty=presence_penalty,
                frequency_penalty=frequency_penalty,
            )
        except Exception as exc:
            return {
                "output": {
                    "content": None,
                    "model": model_id,
                },
                "error": str(exc),
            }

        return {
            "output": {
                "content": resp.content,
                "model": resp.model or model_id,
            },
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            },
            "error": None,
        }

    async def llm_fn(state: dict) -> dict:
        result = await _run_with_retry(
            lambda: _do_llm(state),
            retry_enabled=retry_enabled,
            max_retries=max_retries,
            node_label="LLM",
        )
        # _run_with_retry 失败时返回的是 {"output":..., "error":...}，与成功结构对齐
        return {
            "output": result.get("output", {}),
            "usage": result.get("usage", {}),
        }

    return llm_fn


# ========== end ==========
def _end_node_build(config: dict[str, Any]):
    async def end_fn(state: dict) -> dict:
        return {"output": state.get("output", {})}

    return end_fn


# ========== branch（条件分支） ==========
def _branch_node_build(config: dict[str, Any]):
    """branch 节点：根据条件选择路由。

    config.conditions: [{field, operator, value}]
    config.routes: {true: "node_id", false: "node_id"}
    """
    conditions = config.get("conditions", [])
    routes = config.get("routes", {})

    async def branch_fn(state: dict) -> dict:
        input_data = state.get("input", {})
        matched = _eval_conditions(conditions, input_data)
        return {
            "route": "true" if matched else "false",
            "output": state.get("output", {}),
        }

    def router(state: dict) -> str:
        route_key = state.get("route", "false")
        return routes.get(route_key, routes.get("false", "end"))

    # 把 router 挂到函数上，compiler 会识别
    branch_fn.__router__ = router
    return branch_fn


def _eval_conditions(conditions: list[dict], data: dict) -> bool:
    for cond in conditions:
        field = cond.get("field", "")
        operator = cond.get("operator", "eq")
        expected = cond.get("value")
        actual = data
        for part in field.split("."):
            if isinstance(actual, dict):
                actual = actual.get(part)
            else:
                actual = None
                break
        if not _compare(actual, operator, expected):
            return False
    return True


def _compare(actual, operator: str, expected) -> bool:
    """按操作符对 actual 与 expected 求值。

    支持的操作符：
      - eq / ne：宽松相等（字符串 "123" 与数字 123 视为相等）
      - gt / gte / lt / lte：数值比较，非数值时尝试转换
      - between：expected 为 "min,max" 字符串，闭区间
      - contains / not_contains：字符串包含 / 不包含
      - startswith / endswith：字符串前缀 / 后缀
      - regex：正则匹配（re.search）
      - is_empty / is_not_empty：None、空串、空容器均视为空
      - has_key：expected 为 key 名，actual 为 dict 时判断 key 存在
    """
    # 空值判断类操作符不依赖 expected
    if operator == "is_empty":
        return _is_empty(actual)
    if operator == "is_not_empty":
        return not _is_empty(actual)

    # 以下操作符都需要 actual 非空
    if actual is None:
        return False

    # 数值类操作符：尝试把 actual 转成 float
    if operator in {"gt", "gte", "lt", "lte", "between"}:
        actual_num = _to_number(actual)
        if actual_num is None:
            return False
        if operator == "between":
            # expected 可能是 "min,max" 字符串或 [min, max] 列表
            lo, hi = _parse_range(expected)
            if lo is None or hi is None:
                return False
            return lo <= actual_num <= hi
        expected_num = _to_number(expected)
        if expected_num is None:
            return False
        if operator == "gt":
            return actual_num > expected_num
        if operator == "gte":
            return actual_num >= expected_num
        if operator == "lt":
            return actual_num < expected_num
        if operator == "lte":
            return actual_num <= expected_num

    if operator == "eq":
        return _loose_equal(actual, expected)
    if operator == "ne":
        return not _loose_equal(actual, expected)
    if operator == "contains":
        return _to_str(expected) in _to_str(actual)
    if operator == "not_contains":
        return _to_str(expected) not in _to_str(actual)
    if operator == "startswith":
        return _to_str(actual).startswith(_to_str(expected))
    if operator == "endswith":
        return _to_str(actual).endswith(_to_str(expected))
    if operator == "regex":
        import re

        try:
            return re.search(_to_str(expected), _to_str(actual)) is not None
        except re.error:
            return False
    if operator == "has_key":
        return isinstance(actual, dict) and _to_str(expected) in actual

    # 长度类操作符：对字符串 / 列表 / dict / 元组 / set 取 len
    length_ops = {
        "length_eq",
        "length_ne",
        "length_gt",
        "length_gte",
        "length_lt",
        "length_lte",
        "length_between",
    }
    if operator in length_ops:
        length = _length_of(actual)
        if length is None:
            return False
        if operator == "length_between":
            lo, hi = _parse_range(expected)
            if lo is None or hi is None:
                return False
            return lo <= length <= hi
        expected_num = _to_number(expected)
        if expected_num is None:
            return False
        if operator == "length_eq":
            return length == expected_num
        if operator == "length_ne":
            return length != expected_num
        if operator == "length_gt":
            return length > expected_num
        if operator == "length_gte":
            return length >= expected_num
        if operator == "length_lt":
            return length < expected_num
        if operator == "length_lte":
            return length <= expected_num

    return False


def _length_of(value):
    """对字符串 / 列表 / dict / 元组 / set 返回 len；其他类型返回 None。"""
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value)
    return None


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _to_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _loose_equal(actual, expected) -> bool:
    """宽松相等：字符串与数字之间自动转换；dict 与 JSON 字符串之间自动解析。"""
    if actual == expected:
        return True
    num_actual = _to_number(actual)
    num_expected = _to_number(expected)
    if num_actual is not None and num_expected is not None:
        return num_actual == num_expected
    # dict vs JSON 字符串
    if isinstance(actual, dict) and isinstance(expected, str):
        try:
            import json as _json

            return actual == _json.loads(expected)
        except (ValueError, TypeError):
            return False
    return False


def _parse_range(expected):
    """把 '10,100' 或 [10, 100] 解析为 (lo, hi)，失败返回 (None, None)。"""
    if isinstance(expected, (list, tuple)) and len(expected) == 2:
        lo = _to_number(expected[0])
        hi = _to_number(expected[1])
        return lo, hi
    if isinstance(expected, str):
        parts = [p.strip() for p in expected.split(",")]
        if len(parts) == 2:
            return _to_number(parts[0]), _to_number(parts[1])
    return None, None


# ========== tool（调工具） ==========
def _tool_node_build(config: dict[str, Any]):
    """tool 节点：调用工具资源（走 resource 表解析 + 工具治理网关）。

    config.resource_id: resource 表中 type=tool 的资源 ID
    config.params: {param_name: 值或占位符}

    tool_config.config 约定：
      - endpoint: 完整 URL
      - method: GET / POST / PUT / DELETE
      - headers: 额外请求头（可选）
      - body_field: 把 params 作为 body 的哪个字段传（可选，默认直接作为 json body）
    """
    resource_id = config.get("resource_id", "")
    params_config = config.get("params", {}) or {}
    retry_enabled = bool(config.get("retry_enabled", False))
    max_retries = int(config.get("max_retries", 3) or 3)

    async def _do_tool(state: dict) -> dict:
        resolver = ToolResolverCtx.get()
        tenant_id = TenantIdCtx.get()
        params = _resolve_params(params_config, state)

        if resolver is None or not resource_id:
            return {
                "output": {
                    "result": f"[TOOL stub] resource_id={resource_id} params={params}",
                    "error": None,
                }
            }

        tool_config = resolver(resource_id)
        if tool_config is None:
            return {
                "output": {
                    "result": None,
                    "error": "工具资源不存在、已禁用或当前租户无权访问",
                }
            }

        tool_detail = tool_config.get("config", {}) or {}
        endpoint = tool_detail.get("endpoint", "")
        method = (tool_detail.get("method") or "POST").upper()
        headers = tool_detail.get("headers", {}) or {}
        body_field = tool_detail.get("body_field")

        if not endpoint:
            return {
                "output": {
                    "result": None,
                    "error": "工具资源未配置 endpoint",
                }
            }

        from internal.engine.context import AgentRunContext
        from internal.engine.tool_gateway import GatewayConfig, ToolExecutionError, get_tool_gateway

        ctx = AgentRunContext(
            agent_id=str(tool_config.get("id", "")),
            tenant_id=tenant_id,
            user_id=None,
            conversation_id="",
        )
        gateway = get_tool_gateway()
        cfg = GatewayConfig()

        try:
            if method == "GET":
                result_text = await gateway.invoke_http(
                    method=method,
                    url=endpoint,
                    headers=headers,
                    json_body=None,
                    params=params,
                    context=ctx,
                    tool_name=tool_config.get("name", resource_id),
                    cfg=cfg,
                )
            else:
                json_body = {body_field: params} if body_field else params
                result_text = await gateway.invoke_http(
                    method=method,
                    url=endpoint,
                    headers=headers,
                    json_body=json_body,
                    params=None,
                    context=ctx,
                    tool_name=tool_config.get("name", resource_id),
                    cfg=cfg,
                )
            return {
                "output": {
                    "result": result_text,
                    "error": None,
                }
            }
        except ToolExecutionError as exc:
            return {
                "output": {
                    "result": None,
                    "error": exc.message,
                }
            }

    async def tool_fn(state: dict) -> dict:
        result = await _run_with_retry(
            lambda: _do_tool(state),
            retry_enabled=retry_enabled,
            max_retries=max_retries,
            node_label="TOOL",
        )
        return {"output": result.get("output", {})}

    return tool_fn


# ========== template（Jinja2 文本转换） ==========
def _template_node_build(config: dict[str, Any]):
    """template 节点：渲染 Jinja2 模板。"""
    template = config.get("template", "")

    async def template_fn(state: dict) -> dict:
        # 简化：用 {{#node.output#}} 语法，后续接 Jinja2
        text = template
        for key, value in state.get("input", {}).items():
            text = text.replace(f"{{{{#input.{key}#}}}}", str(value))
        return {"output": {"text": text}}

    return template_fn


# ========== http（HTTP 请求） ==========
def _http_node_build(config: dict[str, Any]):
    """http 节点：发 HTTP 请求（走 SSRF 防护）。

    HTTP 节点通用语义：
      - config.url: 目标 URL，支持 {{#input.xxx#}} 占位符
      - config.method: GET / POST / PUT / DELETE / PATCH
      - config.headers: 额外请求头 KV
      - config.params: Query 参数 KV，运行时拼接到 URL 后面
      - config.body: 请求体（JSON 对象或占位符）
      - config.timeout_seconds: 请求超时秒数（默认 30）
      - config.verify_ssl: 是否校验 TLS 证书（默认 True）
      - config.retry_enabled / max_retries: 节点级失败重试
    """
    url_template = config.get("url", "")
    method = (config.get("method") or "GET").upper()
    headers_config = config.get("headers", {}) or {}
    params_config = config.get("params", {}) or {}
    body_config = config.get("body")
    timeout_seconds = float(config.get("timeout_seconds", 30) or 30)
    retry_enabled = bool(config.get("retry_enabled", False))
    max_retries = int(config.get("max_retries", 3) or 3)
    verify_ssl = bool(config.get("verify_ssl", True))

    async def _do_http(state: dict) -> dict:
        import httpx

        from internal.infrastructure.security.ssrf_guard import validate_outbound_url

        url = _resolve_template(url_template, state)
        headers = _resolve_params(headers_config, state)
        query_params = _resolve_params(params_config, state)
        body = _resolve_template(json.dumps(body_config)) if body_config else None
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            validate_outbound_url(url)
        except Exception as exc:
            return {
                "output": {
                    "status": 0,
                    "body": None,
                    "headers": {},
                    "error": f"URL 不安全：{exc}",
                }
            }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify_ssl) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=query_params or None)
                elif method == "POST":
                    resp = await client.post(url, headers=headers, params=query_params or None, json=body)
                elif method == "PUT":
                    resp = await client.put(url, headers=headers, params=query_params or None, json=body)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers, params=query_params or None)
                elif method == "PATCH":
                    resp = await client.patch(url, headers=headers, params=query_params or None, json=body)
                else:
                    resp = await client.request(
                        method, url, headers=headers, params=query_params or None, json=body
                    )
            # HTTP 4xx/5xx 也算失败；4xx 是业务错误（参数/权限/资源不存在），重试无意义
            if resp.status_code >= 400:
                return {
                    "output": {
                        "status": resp.status_code,
                        "body": resp.text[:8192],
                        "headers": dict(resp.headers),
                    },
                    "error": f"HTTP {resp.status_code}",
                    "retryable": resp.status_code >= 500,
                }
            return {
                "output": {
                    "status": resp.status_code,
                    "body": resp.text[:8192],
                    "headers": dict(resp.headers),
                },
                "error": None,
            }
        except Exception as exc:
            return {
                "output": {
                    "status": 0,
                    "body": None,
                    "headers": {},
                },
                "error": str(exc),
            }

    async def http_fn(state: dict) -> dict:
        result = await _run_with_retry(
            lambda: _do_http(state),
            retry_enabled=retry_enabled,
            max_retries=max_retries,
            node_label="HTTP",
        )
        return {"output": result.get("output", {})}

    return http_fn


def _resolve_template(template: str, state: dict) -> str:
    """把 {{#input.xxx#}} / {{#output.xxx#}} 占位符替换为实际值。"""
    if not isinstance(template, str):
        return template
    result = template
    for key, value in state.get("input", {}).items():
        result = result.replace(f"{{{{#input.{key}#}}}}", str(value))
    for key, value in state.get("output", {}).items():
        if isinstance(value, (str, int, float, bool)):
            result = result.replace(f"{{{{#output.{key}#}}}}", str(value))
    return result


# ========== retrieval（RAG 检索） ==========
def _retrieval_node_build(config: dict[str, Any]):
    """retrieval 节点：从知识库检索相关文档。

    config.knowledge_base_id: knowledge 资源 ID（运行时通过 KnowledgeResolverCtx 解析为 document_ids）
    config.query_field: 从 input 取哪个字段作为检索 query（默认 query）
    config.top_k: 返回前 K 条（默认 5）
    config.enable_rerank / enable_query_rewrite: 透传给 RetrievalService，默认 True
    """
    kb_id = config.get("knowledge_base_id", "")
    query_field = config.get("query_field", "query")
    top_k = int(config.get("top_k", 5))
    enable_rerank = bool(config.get("enable_rerank", True))
    enable_query_rewrite = bool(config.get("enable_query_rewrite", True))

    async def retrieval_fn(state: dict) -> dict:
        input_data = state.get("input", {})
        query = input_data.get(query_field, "") or ""
        retrieval_service = RetrievalServiceCtx.get()
        knowledge_resolver = KnowledgeResolverCtx.get()

        # 未注入依赖时返回 stub，保持开发态可跑
        if retrieval_service is None or knowledge_resolver is None or not kb_id:
            stub_results = [
                {
                    "doc_id": f"doc_{i}",
                    "score": 1.0 - i * 0.1,
                    "content": f"[RAG stub] kb={kb_id or 'unset'} query={query} top_k={top_k} doc_{i}",
                }
                for i in range(top_k)
            ]
            return {
                "output": {
                    "results": stub_results,
                    "context_text": "",
                    "count": len(stub_results),
                    "mode": "stub",
                }
            }

        document_ids = knowledge_resolver(kb_id)
        if not document_ids:
            return {
                "output": {
                    "results": [],
                    "context_text": "",
                    "count": 0,
                    "mode": "no_permission_or_empty",
                }
            }

        result = await retrieval_service.search(
            query=str(query),
            document_ids=document_ids,
            top_k=top_k,
            enable_rerank=enable_rerank,
            enable_query_rewrite=enable_query_rewrite,
        )
        results = [
            {
                "doc_id": str(chunk.document_id),
                "chunk_index": chunk.chunk_index,
                "score": chunk.score,
                "content": chunk.content,
                "heading_path": chunk.metadata.get("heading_path") or [],
            }
            for chunk in result.chunks
        ]
        return {
            "output": {
                "results": results,
                "context_text": result.context_text,
                "standalone_query": result.standalone_query,
                "count": len(results),
                "mode": "retrieval",
            }
        }

    return retrieval_fn


# ========== human_task（人审节点） ==========
def _human_task_node_build(config: dict[str, Any]):
    """human_task 节点：暂停图执行，等待人工审批。

    使用 LangGraph interrupt 暂停图执行。interrupt 抛出后，图状态被 checkpointer 保存，
    外部通过 Command(resume=...) 传入审批结果恢复执行。

    config.assignee_role: 指派角色（如 reviewer / approver）
    config.instructions: 审批说明
    config.timeout_seconds: 审批超时秒数（默认 3600s）
    config.timeout_action: 超时动作，"fail"（默认）或 "continue"（自动通过）
    """
    from langgraph.types import interrupt

    assignee_role = config.get("assignee_role", "reviewer")
    instructions = config.get("instructions", "")
    timeout_seconds = int(config.get("timeout_seconds", 3600) or 3600)
    timeout_action = config.get("timeout_action", "fail")

    async def human_task_fn(state: dict) -> dict:
        snapshot = state.get("input", {})
        # interrupt 会暂停图执行，下次 resume 时返回值就是传入的 resume 参数
        decision = interrupt({
            "type": "human_approval",
            "assignee_role": assignee_role,
            "instructions": instructions,
            "timeout_seconds": timeout_seconds,
            "timeout_action": timeout_action,
            "snapshot": snapshot,
        })
        # decision 形如 {"approved": bool, "comment": str}
        approved = bool(decision.get("approved", False)) if isinstance(decision, dict) else False
        comment = decision.get("comment", "") if isinstance(decision, dict) else ""
        # 上游 runner 在超时后会按 timeout_action 构造 decision：
        #   - fail: 直接抛错，不会走到这里
        #   - continue: 传入 {"approved": True, "comment": "auto approved by timeout"}
        return {
            "output": {
                "status": "approved" if approved else "rejected",
                "assignee_role": assignee_role,
                "comment": comment,
                "timeout_seconds": timeout_seconds,
                "timeout_action": timeout_action,
                "snapshot": snapshot,
            }
        }

    return human_task_fn


# ========== subgraph（子图） ==========
def _subgraph_node_build(config: dict[str, Any]):
    """subgraph 节点：嵌套调用另一个 application 的 graph。

    config.application_id: 要嵌套调用的应用 ID
    config.input_mapping: {parent_field: child_field}，把父 state.input 映射为子图 input
    """
    application_id = config.get("application_id", "")
    input_mapping = config.get("input_mapping", {}) or {}

    async def subgraph_fn(state: dict) -> dict:
        loader = SubgraphLoaderCtx.get()
        input_data = state.get("input", {})

        if loader is None or not application_id:
            mapped_input = _map_input(input_data, input_mapping)
            return {
                "output": {
                    "application_id": application_id,
                    "input": mapped_input,
                    "result": "[SUBGRAPH stub] 未注入 subgraph loader",
                }
            }

        graph_json = loader(application_id)
        if not graph_json:
            return {
                "output": {
                    "application_id": application_id,
                    "error": "子图不存在或未发布",
                }
            }

        from internal.engine.graph.compiler import compile_graph

        compiled = compile_graph(graph_json)
        mapped_input = _map_input(input_data, input_mapping)
        child_state = await compiled.ainvoke({"input": mapped_input})
        child_output = child_state.get("output", {}) if isinstance(child_state, dict) else {}

        return {
            "output": {
                "application_id": application_id,
                "result": child_output,
            }
        }

    return subgraph_fn


def _map_input(parent_input: dict, mapping: dict) -> dict:
    """父 input 字段按 mapping 重命名为子图 input 字段。

    mapping 为空时整体透传。
    """
    if not mapping:
        return dict(parent_input)
    return {
        child_key: parent_input.get(parent_key)
        for parent_key, child_key in mapping.items()
    }


def _resolve_params(params: dict, state: dict) -> dict:
    """把 {{#node.output#}} 占位符替换为实际值。"""
    result = {}
    for key, value in params.items():
        if isinstance(value, str) and value.startswith("{{#"):
            # 简化：从 state.input 取
            result[key] = state.get("input", {}).get(value[3:-3], value)
        else:
            result[key] = value
    return result


# ========== 注册 ==========
register_node(
    NodePlugin(
        type="start",
        version="1.0",
        config_schema={},
        build=_start_node_build,
        input_ports=[],
        output_ports=[PortSpec(name="output", type="object")],
    )
)

register_node(
    NodePlugin(
        type="llm",
        version="1.0",
        config_schema={
            "model_id": {"type": "string"},
            "system_prompt": {"type": "string"},
            "user_prompt": {"type": "string"},
            "temperature": {"type": "number", "default": 0.7},
            "max_tokens": {"type": "number"},
            "top_p": {"type": "number"},
            "presence_penalty": {"type": "number"},
            "frequency_penalty": {"type": "number"},
            "response_format_json": {"type": "boolean", "default": False},
            "retry_enabled": {"type": "boolean", "default": False},
            "max_retries": {"type": "number", "default": 3},
        },
        build=_llm_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[
            PortSpec(name="output", type="object"),
            PortSpec(name="usage", type="object"),
        ],
    )
)

register_node(
    NodePlugin(
        type="end",
        version="1.0",
        config_schema={},
        build=_end_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[],
    )
)

register_node(
    NodePlugin(
        type="branch",
        version="1.0",
        config_schema={
            "conditions": {"type": "array"},
            "routes": {"type": "object"},
        },
        build=_branch_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[
            PortSpec(name="true", type="object"),
            PortSpec(name="false", type="object"),
        ],
    )
)

register_node(
    NodePlugin(
        type="tool",
        version="1.0",
        config_schema={
            "resource_id": {"type": "string"},
            "params": {"type": "object"},
            "retry_enabled": {"type": "boolean", "default": False},
            "max_retries": {"type": "number", "default": 3},
        },
        build=_tool_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[PortSpec(name="output", type="object")],
    )
)

register_node(
    NodePlugin(
        type="template",
        version="1.0",
        config_schema={
            "template": {"type": "string"},
        },
        build=_template_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[PortSpec(name="text", type="string")],
    )
)

register_node(
    NodePlugin(
        type="http",
        version="1.0",
        config_schema={
            "url": {"type": "string"},
            "method": {"type": "string", "default": "GET"},
            "headers": {"type": "object"},
            "params": {"type": "object"},
            "body": {"type": "object"},
            "timeout_seconds": {"type": "number", "default": 30},
            "verify_ssl": {"type": "boolean", "default": True},
            "retry_enabled": {"type": "boolean", "default": False},
            "max_retries": {"type": "number", "default": 3},
        },
        build=_http_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[
            PortSpec(name="status", type="number"),
            PortSpec(name="body", type="object"),
        ],
    )
)

register_node(
    NodePlugin(
        type="retrieval",
        version="1.0",
        config_schema={
            "knowledge_base_id": {"type": "string"},
            "query_field": {"type": "string", "default": "query"},
            "top_k": {"type": "number", "default": 5},
        },
        build=_retrieval_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[
            PortSpec(name="results", type="array"),
            PortSpec(name="count", type="number"),
        ],
    )
)

register_node(
    NodePlugin(
        type="human_task",
        version="1.0",
        config_schema={
            "assignee_role": {"type": "string", "default": "reviewer"},
            "instructions": {"type": "string"},
            "timeout_seconds": {"type": "number", "default": 3600},
            "timeout_action": {"type": "string", "default": "fail"},
        },
        build=_human_task_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[PortSpec(name="output", type="object")],
    )
)

register_node(
    NodePlugin(
        type="subgraph",
        version="1.0",
        config_schema={
            "application_id": {"type": "string"},
            "input_mapping": {"type": "object"},
        },
        build=_subgraph_node_build,
        input_ports=[PortSpec(name="input", type="object")],
        output_ports=[PortSpec(name="output", type="object")],
    )
)
