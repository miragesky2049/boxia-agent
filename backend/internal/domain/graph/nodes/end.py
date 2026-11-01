"""END 节点：把求值后的入参或配置的 content 模板作为最终输出。"""

from __future__ import annotations

from typing import Any

from internal.domain.canvas.expression import Literal, TemplatedString
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class EndNodeHandler(NodeHandler):
    type_name = NodeType.END.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        # coze 真实格式：END 通过 inputParameters 显式声明输出字段，inputs 已是求值结果
        if ctx.inputs:
            return NodeResult(outputs=dict(ctx.inputs))

        # 前端简化格式：只配置了一个 content 模板（如 {{llm-xxx.output.output}}）
        content = _unwrap_content(ctx.config.get("content"))
        if content is None or content == "":
            return NodeResult(outputs={})

        if isinstance(content, str) and ctx.evaluator is not None and ctx.eval_context is not None:
            content = ctx.evaluator.template.eval_template(content, ctx.eval_context)

        return NodeResult(outputs={"output": content})


def _unwrap_content(value: Any) -> Any:
    """把 content 字段的 Expr 包装脱壳成实际值。"""
    if isinstance(value, Literal):
        return value.value
    if isinstance(value, TemplatedString):
        return value.template
    return value


register_node_handler(EndNodeHandler())
