"""文本处理节点（coze type=15）：字符串模板拼接 / 大小写 / 截取。

config 约定：
- operation: "concat" / "upper" / "lower" / "slice" / "replace"
- template: concat 时的模板（{{input}} 占位符）
- start / end: slice 时的下标
- find / replaceWith: replace 时的查找串与替换串
"""

from __future__ import annotations

from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class TextProcessorNodeHandler(NodeHandler):
    type_name = NodeType.TEXT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        op = str(ctx.config.get("operation") or "concat")
        text = str(ctx.inputs.get("input") or "")

        result: Any = text
        if op == "upper":
            result = text.upper()
        elif op == "lower":
            result = text.lower()
        elif op == "slice":
            start = int(ctx.config.get("start") or 0)
            end = ctx.config.get("end")
            end_int = int(end) if end is not None else None
            result = text[start:end_int]
        elif op == "replace":
            find = str(ctx.config.get("find") or "")
            repl = str(ctx.config.get("replaceWith") or "")
            result = text.replace(find, repl)
        else:  # concat
            template = str(ctx.config.get("template") or "{{input}}")
            result = template.replace("{{input}}", text)

        return NodeResult(outputs={"output": result})


register_node_handler(TextProcessorNodeHandler())
