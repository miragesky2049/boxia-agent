"""输出节点（coze type=13）：对话流中的中间消息输出。

与「创建消息」节点的区别：
- 输出节点是对话流语义节点，面向聊天界面：内容会实时推送为 assistant 消息
- 创建消息节点是通用编排节点，只做消息落库，不参与聊天渲染

运行时行为：
1. 渲染 `content` 模板（支持 {{node.output.field}}）
2. 通过 emit_event 推送 `output_message` SSE 事件
3. 当前会话存在时把消息落库（assistant），保证刷新后历史完整
"""

from __future__ import annotations

import json
import logging
from typing import Any

from internal.domain.agent.model import Message
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


def to_text(value: Any) -> str:
    """把模板求值结果转成可展示文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_content(ctx: NodeContext, key: str) -> str:
    """渲染节点配置中的模板字段；求值器缺失时退回原始值。"""
    raw = (ctx.config or {}).get(key, "")
    if ctx.evaluator is not None and ctx.eval_context is not None:
        raw = ctx.evaluator.resolve_config(raw, ctx.eval_context)
    text = to_text(raw)
    # 前端把模板存成普通字符串，这里显式做 {{...}} 插值
    if ctx.evaluator is not None and ctx.eval_context is not None and "{{" in text:
        text = ctx.evaluator.template.eval_template(text, ctx.eval_context)
    return text


def render_variable_map(ctx: NodeContext, raw: Any) -> dict[str, Any]:
    """渲染输出变量表：支持 [{key, value}] 或 {key: template}。"""
    if isinstance(raw, list):
        pairs = [
            (str(item.get("key") or item.get("name") or ""), item.get("value"))
            for item in raw
            if isinstance(item, dict)
        ]
    elif isinstance(raw, dict):
        pairs = list(raw.items())
    else:
        return {}

    rendered: dict[str, Any] = {}
    for key, value in pairs:
        if not key:
            continue
        if ctx.evaluator is not None and ctx.eval_context is not None:
            value = ctx.evaluator.resolve_config(value, ctx.eval_context)
            text = to_text(value)
            if "{{" in text:
                value = ctx.evaluator.template.eval_template(text, ctx.eval_context)
        rendered[key] = value
    return rendered


async def persist_assistant_message(
    ctx: NodeContext,
    content: str,
    *,
    source: str,
) -> None:
    """把 assistant 消息落库；无会话或仓储缺失时静默跳过。

    source 标记消息来源（output_node / end_node），便于排查与去重。
    """
    conversation_id = ctx.env.conversation_id
    if conversation_id is None or not ctx.services.has("message_repo"):
        return
    try:
        await ctx.services.get("message_repo").append(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                metadata={
                    "run_id": str(ctx.env.run_id),
                    "node_id": ctx.node_id,
                    "source": source,
                },
            )
        )
    except Exception:  # noqa: BLE001
        # 消息落库失败不应中断流程：消息已经通过 SSE 推送给前端
        logger.exception(
            "节点写消息失败: node=%s conversation=%s source=%s",
            ctx.node_id,
            conversation_id,
            source,
        )


class OutputNodeHandler(NodeHandler):
    """type=13: 向对话输出一条中间消息。"""

    type_name = NodeType.OUTPUT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        content = render_content(ctx, "content")

        if ctx.emit_event is not None:
            await ctx.emit_event(
                "output_message",
                {
                    "content": content,
                    "role": "assistant",
                    "stream": bool((ctx.config or {}).get("stream", False)),
                },
            )

        await persist_assistant_message(ctx, content, source="output_node")

        outputs: dict[str, Any] = {"output": content}
        outputs.update(render_variable_map(ctx, (ctx.config or {}).get("outputVariables")))
        return NodeResult(outputs=outputs)


register_node_handler(OutputNodeHandler())
