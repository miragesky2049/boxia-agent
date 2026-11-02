"""输入节点（coze type=30）：对话流内等待用户输入的轻量形态。

复用问答节点的 interrupt/resume 内核，固定为自由文本回答；
配置项 prompt 作为提示语，兼容 question 字段。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.graph.nodes.question import (
    ANSWER_TYPE_DIRECT,
    QuestionNodeHandler,
)


class InputNodeHandler(QuestionNodeHandler):
    """type=30: 等待用户输入一段文本。"""

    type_name = NodeType.INPUT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = dict(ctx.config or {})
        if not config.get("question"):
            config["question"] = config.get("prompt") or "请输入内容"
        config["answerType"] = ANSWER_TYPE_DIRECT
        config["options"] = ""

        normalized = NodeContext(
            node_id=ctx.node_id,
            node_type=ctx.node_type,
            inputs=ctx.inputs,
            config=config,
            env=ctx.env,
            services=ctx.services,
            subgraph=ctx.subgraph,
            eval_context=ctx.eval_context,
            evaluator=ctx.evaluator,
            emit_event=ctx.emit_event,
        )
        return await super().run(normalized)


register_node_handler(InputNodeHandler())
