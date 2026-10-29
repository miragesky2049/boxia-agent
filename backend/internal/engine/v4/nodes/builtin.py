"""内置节点：start / llm / end / branch / tool / template / http。"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from internal.engine.llm import LLMClient
from internal.engine.v4.registry import NodePlugin, PortSpec, register_node

logger = logging.getLogger(__name__)

# 运行时模型解析器：由 GraphRunner 在 invoke 前注入（asyncio contextvar）
# 节点无需感知会话，只通过此上下文拿到 LLMClient
ModelResolverCtx: ContextVar[Any] = ContextVar("v4_model_resolver", default=None)

# 运行时子图加载器：由 GraphRunner 注入，签名 (application_id: str) -> dict（返回 graph JSON）
# 节点通过此上下文递归加载并执行目标 application 的 graph
SubgraphLoaderCtx: ContextVar[Any] = ContextVar("v4_subgraph_loader", default=None)

# 运行时 tool 资源解析器：由 GraphRunner 注入，签名 (resource_id: str) -> dict | None
# 返回 tool 的 config（含 endpoint / method / params_schema），无权访问或不存在时返回 None
ToolResolverCtx: ContextVar[Any] = ContextVar("v4_tool_resolver", default=None)

# 当前租户 ID：由 GraphRunner 在 invoke 前注入，tool/http 节点构造 AgentRunContext 用
TenantIdCtx: ContextVar[Any] = ContextVar("v4_tenant_id", default=None)


# ========== start ==========
def _start_node_build(config: dict[str, Any]):
    async def start_fn(state: dict) -> dict:
        return {"input": state.get("input", {})}

    return start_fn


# ========== llm ==========
def _llm_node_build(node_config: dict[str, Any]):
    """llm 节点：调用模型网关。

    LLMClient 通过 ModelResolverCtx 注入，节点工厂闭包捕获 node_config。
    """
    system_prompt: str = node_config.get("system_prompt", "")
    model_id: str = node_config.get("model_id", "")
    temperature: float = node_config.get("temperature", 0.7)

    async def llm_fn(state: dict) -> dict:
        resolver = ModelResolverCtx.get()
        user_input = state.get("input", {})
        user_message = user_input.get("message") or user_input.get("query") or str(user_input)

        if resolver is None or not model_id:
            return {
                "output": {
                    "content": f"[LLM stub] model={model_id} input={user_message[:80]}",
                    "model": model_id,
                }
            }

        client: LLMClient = resolver(model_id)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(user_message)})

        resp = await client.chat(
            messages=messages,
            temperature=temperature,
        )
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
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "contains":
        return actual is not None and expected in actual
    return False


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

    async def tool_fn(state: dict) -> dict:
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

    config.url: 目标 URL
    config.method: GET / POST / PUT / DELETE
    config.headers: 额外请求头
    config.body: 请求体（JSON 对象或占位符）
    """
    url_template = config.get("url", "")
    method = (config.get("method") or "GET").upper()
    headers_config = config.get("headers", {}) or {}
    body_config = config.get("body")

    async def http_fn(state: dict) -> dict:
        import httpx

        from internal.infrastructure.security.ssrf_guard import validate_outbound_url

        url = _resolve_template(url_template, state)
        headers = _resolve_params(headers_config, state)
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers)
                elif method == "POST":
                    resp = await client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    resp = await client.put(url, headers=headers, json=body)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    resp = await client.request(method, url, headers=headers, json=body)
            return {
                "output": {
                    "status": resp.status_code,
                    "body": resp.text[:8192],
                    "headers": dict(resp.headers),
                    "error": None,
                }
            }
        except Exception as exc:
            return {
                "output": {
                    "status": 0,
                    "body": None,
                    "headers": {},
                    "error": str(exc),
                }
            }

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

    config.knowledge_base_id: 知识库 ID
    config.query_field: 从 input 取哪个字段作为检索 query（默认 query）
    config.top_k: 返回前 K 条（默认 5）
    """
    kb_id = config.get("knowledge_base_id", "")
    query_field = config.get("query_field", "query")
    top_k = int(config.get("top_k", 5))

    async def retrieval_fn(state: dict) -> dict:
        input_data = state.get("input", {})
        query = input_data.get(query_field, "")
        # TODO: 接向量检索引擎，首期返回 stub
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
                "count": len(stub_results),
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
    """
    from langgraph.types import interrupt

    assignee_role = config.get("assignee_role", "reviewer")
    instructions = config.get("instructions", "")

    async def human_task_fn(state: dict) -> dict:
        snapshot = state.get("input", {})
        # interrupt 会暂停图执行，下次 resume 时返回值就是传入的 resume 参数
        decision = interrupt({
            "type": "human_approval",
            "assignee_role": assignee_role,
            "instructions": instructions,
            "snapshot": snapshot,
        })
        # decision 形如 {"approved": bool, "comment": str}
        approved = bool(decision.get("approved", False)) if isinstance(decision, dict) else False
        comment = decision.get("comment", "") if isinstance(decision, dict) else ""
        return {
            "output": {
                "status": "approved" if approved else "rejected",
                "assignee_role": assignee_role,
                "comment": comment,
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

        from internal.engine.v4.compiler import compile_graph

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
            "temperature": {"type": "number", "default": 0.7},
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
