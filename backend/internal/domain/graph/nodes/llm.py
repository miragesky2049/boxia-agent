"""LLM 节点：调用大模型。

config 约定（来自 coze llmParam 压平后的结构）：
- modleName: 模型显示名（注意 coze 拼写是 modleName，不是 modelName）
- temperature / maxTokens / responseFormat: 采样参数
- prompt: 用户提示词模板（{{input}} 占位符在 inputs.input 求值后替换）
- systemPrompt: 系统提示词
"""

from __future__ import annotations

import logging
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class LLMNodeHandler(NodeHandler):
    type_name = NodeType.LLM.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        prompt_template = str(config.get("prompt") or "")
        system_prompt = str(config.get("systemPrompt") or "")

        # 用户输入：inputs.input 是 Ref 表达式，已求值为 START.USER_INPUT
        user_input = ctx.inputs.get("input")
        user_message = _render_prompt(prompt_template, user_input)

        # 未注入 llm 服务时返回 stub，保持开发态可跑
        if not ctx.services.has("llm"):
            return NodeResult(outputs={
                "output": f"[LLM stub] model={config.get('modleName')} input={str(user_message)[:80]}",
            })

        llm_service = ctx.services.get("llm")
        model_id = str(config.get("modleName") or "")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(user_message)})

        temperature = _to_float(config.get("temperature"), 0.7)
        max_tokens = _to_int(config.get("maxTokens"))
        response_format = {"type": "json_object"} if str(config.get("responseFormat")) == "2" else None

        try:
            resp = await llm_service.chat(
                messages=messages,
                model=model_id,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except Exception as exc:
            # 抛异常让 Runtime 按 ErrorPolicy 处理（重试 / 跳过 / 中断）
            logger.exception("LLM 调用失败: node=%s", ctx.node_id)
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc

        usage: dict[str, int] | None = None
        if hasattr(resp, "usage") and resp.usage is not None:
            usage = {
                "prompt_tokens": int(getattr(resp.usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(resp.usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(resp.usage, "total_tokens", 0) or 0),
            }

        output_text = getattr(resp, "content", str(resp))
        return NodeResult(
            outputs={"output": output_text, "model": model_id},
            usage=usage,
        )


def _render_prompt(template: str, user_input: Any) -> str:
    """把 prompt 模板里的 {{input}} 占位符替换为实际用户输入。"""
    if not template:
        return str(user_input) if user_input is not None else ""
    return template.replace("{{input}}", str(user_input or ""))


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


register_node_handler(LLMNodeHandler())
