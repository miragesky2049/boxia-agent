"""工作流即工具的入参 schema 提取（0074 PRD F7.1，20261107）。

已发布 workflow 应用被智能体挂载为工具时，工具入参 JSON Schema 来自其
start 节点声明的"启动参数"（coze 画布形态：节点 data.inputs.params，
值经 literal 包装）。纯函数、只读，不依赖运行时。
"""

from __future__ import annotations

from typing import Any

START_NODE_TYPE_CODE = "1"

# start 参数类型 → JSON Schema 类型；未知类型按 string 收口（宽容读画布）
_JSON_TYPE_MAP = {
    "string": "string",
    "text": "string",
    "number": "number",
    "integer": "integer",
    "int": "integer",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "object": "object",
    "array": "array",
    "file": "string",
    "image": "string",
}


def build_start_input_schema(graph: dict[str, Any]) -> dict[str, Any]:
    """从画布 JSON 提取 start 节点启动参数，构造 OpenAI tool parameters 的 JSON Schema。

    找不到 start 节点或无参数声明时返回空对象 schema（工具仍可被无参调用，
    由工作流内部对缺失变量按默认值处理）。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in _iter_start_params(graph):
        name = str(param.get("name") or param.get("key") or "").strip()
        if not name:
            continue
        schema_type = _JSON_TYPE_MAP.get(str(param.get("type") or "").lower(), "string")
        entry: dict[str, Any] = {"type": schema_type}
        description = str(param.get("description") or param.get("desc") or "").strip()
        if description:
            entry["description"] = description
        properties[name] = entry
        # coze 画布 required 缺省视为必填（启动参数不填则工作流跑不起来）
        if param.get("required", True):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _iter_start_params(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """定位 start 节点并取出其 params 列表（兼容 literal 包装与裸形态）。"""
    for node in graph.get("nodes") or []:
        if str(node.get("type")) != START_NODE_TYPE_CODE:
            continue
        inputs = (node.get("data") or {}).get("inputs") or {}
        raw = inputs.get("params")
        if raw is None:
            raw = inputs.get("variables")
        content = _unwrap_literal(raw)
        if isinstance(content, list):
            return [item for item in content if isinstance(item, dict)]
    return []


def _unwrap_literal(raw: Any) -> Any:
    """脱壳 coze 引用/字面量包装：{value: {type: "literal", content: X}} → X。"""
    if isinstance(raw, dict) and "value" in raw:
        inner = raw.get("value")
        if isinstance(inner, dict) and inner.get("type") == "literal":
            return inner.get("content")
        return inner
    return raw
