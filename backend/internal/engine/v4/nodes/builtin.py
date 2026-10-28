"""内置节点：start / llm / end / branch / tool / template / http。"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

from internal.engine.llm import LLMClient
from internal.engine.v4.registry import NodePlugin, PortSpec, register_node

logger = logging.getLogger(__name__)

# 运行时模型解析器：由 GraphRunner 在 invoke 前注入（asyncio contextvar）
# 节点无需感知会话，只通过此上下文拿到 LLMClient
ModelResolverCtx: ContextVar[Any] = ContextVar("v4_model_resolver", default=None)


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
    """tool 节点：调用工具（走工具治理网关）。

    config.tool_id: 资源 ID
    config.params: {param_name: "{{#node.output#}}"}
    """

    async def tool_fn(state: dict) -> dict:
        # TODO: 接工具治理网关
        params = _resolve_params(config.get("params", {}), state)
        return {
            "output": {
                "result": f"[TOOL] {config.get('tool_id', 'unknown')} params={params}",
                "error": None,
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
    """http 节点：发 HTTP 请求（走 SSRF 防护）。"""

    async def http_fn(state: dict) -> dict:
        # TODO: 接 SSRF 防护 + 工具治理网关
        return {
            "output": {
                "status": 200,
                "body": f"[HTTP] {config.get('method', 'GET')} {config.get('url', '')}",
                "headers": {},
            }
        }

    return http_fn


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
