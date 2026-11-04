"""END 节点：把求值后的入参或配置的 content 模板作为最终输出。"""

from __future__ import annotations

from typing import Any

from internal.domain.canvas.expression import Literal, TemplatedString
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.graph.nodes.output import persist_assistant_message, to_text


class EndNodeHandler(NodeHandler):
    type_name = NodeType.END.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}
        return_type = str(config.get("returnType") or "").strip().lower()

        # 返回变量：coze 通过 inputParameters 显式声明输出字段，inputs 已是求值结果
        if return_type == "variables":
            return NodeResult(outputs=dict(ctx.inputs))

        content = _unwrap_content(config.get("content"))
        if return_type == "text" and content not in (None, ""):
            content = self._render(content, ctx)
            if bool(config.get("stream")) and ctx.emit_event is not None:
                await ctx.emit_event("output_message", {
                    "content": content,
                    "role": "assistant",
                    "stream": True,
                })
                # 流式最终文本也需落库：runtime 会按 emitted_outputs 去重，
                # 否则刷新后历史里缺失本轮最终回答。
                await persist_assistant_message(ctx, to_text(content), source="end_node")
            return NodeResult(outputs={"output": content})

        # 未声明返回类型时保持旧行为：优先用上游入参，其次用 content 模板
        if ctx.inputs:
            return NodeResult(outputs=dict(ctx.inputs))
        if content is None or content == "":
            return NodeResult(outputs={})
        content = self._render(content, ctx)
        return NodeResult(outputs={"output": content})

    @staticmethod
    def _render(content: Any, ctx: NodeContext) -> Any:
        """渲染 content 模板；非字符串原样返回。"""
        if isinstance(content, str) and ctx.evaluator is not None and ctx.eval_context is not None:
            return ctx.evaluator.template.eval_template(content, ctx.eval_context)
        return content


def _unwrap_content(value: Any) -> Any:
    """把 content 字段的 Expr 包装脱壳成实际值。"""
    if isinstance(value, Literal):
        return value.value
    if isinstance(value, TemplatedString):
        return value.template
    return value


register_node_handler(EndNodeHandler())
