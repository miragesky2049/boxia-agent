"""JSON 工具节点：JSON_PARSER (type=59) / JSON_STRINGIFY (type=58)。"""

from __future__ import annotations

import json
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class JsonParserNodeHandler(NodeHandler):
    """把字符串解析成对象。"""

    type_name = NodeType.JSON_PARSER.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        raw = ctx.inputs.get("input")
        if raw is None:
            return NodeResult(outputs={"output": None, "error": "json_parser 缺少 input"})
        if isinstance(raw, (dict, list)):
            return NodeResult(outputs={"output": raw})
        try:
            parsed = json.loads(str(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"JSON 解析失败: {exc}") from exc
        return NodeResult(outputs={"output": parsed})


class JsonStringifyNodeHandler(NodeHandler):
    """把对象序列化成字符串。"""

    type_name = NodeType.JSON_STRINGIFY.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        obj = ctx.inputs.get("input")
        try:
            text = json.dumps(obj, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"JSON 序列化失败: {exc}") from exc
        return NodeResult(outputs={"output": text})


register_node_handler(JsonParserNodeHandler())
register_node_handler(JsonStringifyNodeHandler())
