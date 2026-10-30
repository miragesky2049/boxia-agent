"""LLM 节点：调用大模型，支持 ReAct 工具调用循环。

config 约定（来自 coze llmParam 压平后的结构）：
- modleName: 模型显示名（注意 coze 拼写是 modleName，不是 modelName）
- temperature / maxTokens / responseFormat: 采样参数
- prompt: 用户提示词模板，支持 {{当前节点.input}} 和 {{上游节点.output.field}} 引用
- systemPrompt: 系统提示词，同上
- tools: 可选，向模型暴露的工具 schema 列表（OpenAI tools 数组项）
  每个元素是 dict：{name, description, parameters: JSON-Schema}
- maxToolRounds: 可选，ReAct 最大轮次（默认 5，防死循环）

求值顺序：
1. 先把 prompt 里的 {{input}} 占位符替换成当前节点的 inputs["input"]（coze 约定）
2. 再用 ExpressionEvaluator 求值 {{node.output.field}} 这类模板引用

工具执行：通过 ctx.services.get("tool_executor") 拿执行器；
    tool_executor(name: str, arguments: dict) -> str，返回值文本回灌给 LLM。
    未注册时 LLM 仍可声明 tool_calls，但回灌文本为 "[error] 工具未注册"。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from internal.domain.canvas.expression import Expr, Literal, TemplatedString
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.engine.llm import LLMToolSpec

logger = logging.getLogger(__name__)

# ReAct 最大轮次：防止 LLM 陷入死循环
DEFAULT_MAX_TOOL_ROUNDS = 5


class LLMNodeHandler(NodeHandler):
    type_name = NodeType.LLM.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        llm_param = config.get("llmParam") if isinstance(config.get("llmParam"), dict) else {}

        def _pick(*keys: str) -> Any:
            """优先从 config 顶层取（前端简化格式），再从 llmParam 取（coze 真实格式）。"""
            for key in keys:
                if key in config and config[key] not in (None, ""):
                    return config[key]
                if key in llm_param and llm_param[key] not in (None, ""):
                    return llm_param[key]
            return None

        prompt_template = _to_str(_pick("prompt"))
        system_prompt_template = _to_str(_pick("systemPrompt"))
        model_id = _to_str(_pick("modleName", "modelName")) or ""
        temperature_raw = _pick("temperature")
        max_tokens_raw = _pick("maxTokens")
        response_format_raw = _pick("responseFormat")
        tools_raw = _pick("tools")
        max_rounds = _to_int(_pick("maxToolRounds")) or DEFAULT_MAX_TOOL_ROUNDS

        user_input = ctx.inputs.get("input")

        # 第一步：替换 {{input}} 占位符（coze 约定的当前节点输入引用）
        prompt_text = prompt_template.replace("{{input}}", str(user_input or ""))
        system_prompt = system_prompt_template.replace("{{input}}", str(user_input or ""))

        # 第二步：用 evaluator 求值 {{node.output.field}} 这类模板引用
        if ctx.evaluator is not None and ctx.eval_context is not None:
            prompt_text = str(
                ctx.evaluator.resolve_config(prompt_text, ctx.eval_context) or ""
            )
            system_prompt = str(
                ctx.evaluator.resolve_config(system_prompt, ctx.eval_context) or ""
            )

        # 未注入 llm 服务时返回 stub，保持开发态可跑
        if not ctx.services.has("llm"):
            return NodeResult(outputs={
                "output": f"[LLM stub] model={model_id} input={str(prompt_text)[:80]}",
            })

        llm_service = ctx.services.get("llm")
        tool_specs = _build_tool_specs(tools_raw)
        tool_executor = ctx.services.get("tool_executor") if ctx.services.has("tool_executor") else None

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(prompt_text)})

        temperature = _to_float(temperature_raw, 0.7)
        max_tokens = _to_int(max_tokens_raw)
        response_format = {"type": "json_object"} if str(response_format_raw) == "2" else None

        # ReAct 循环：调 LLM → 若返回 tool_calls 则执行 → 把结果回灌 → 再调
        aggregated_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        final_content = ""
        tool_call_log: list[dict[str, Any]] = []

        chat_kwargs: dict[str, Any] = {
            "messages": messages,
            "model": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if tool_specs:
            chat_kwargs["tools"] = tool_specs

        try:
            for round_idx in range(max_rounds):
                resp = await llm_service.chat(**chat_kwargs)
                _accumulate_usage(aggregated_usage, resp)

                tool_calls = list(getattr(resp, "tool_calls", None) or [])
                if not tool_calls:
                    final_content = getattr(resp, "content", "") or ""
                    break

                # 把 assistant 的 tool_calls 追加进 messages
                messages.append({
                    "role": "assistant",
                    "content": getattr(resp, "content", "") or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                # 逐个执行工具并回灌 role=tool 消息
                for tc in tool_calls:
                    observation = await _execute_one_tool(
                        tool_executor, tc.function.name, tc.function.arguments,
                    )
                    tool_call_log.append({
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                        "observation": observation,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": observation,
                    })
            else:
                final_content = "（达到最大工具调用轮次，已停止）"
        except Exception as exc:
            logger.exception("LLM 调用失败: node=%s", ctx.node_id)
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc

        outputs: dict[str, Any] = {
            "output": final_content,
            "model": model_id,
        }
        if tool_call_log:
            outputs["tool_calls"] = tool_call_log

        return NodeResult(outputs=outputs, usage=aggregated_usage)


def _build_tool_specs(tools_raw: Any) -> list[LLMToolSpec]:
    """把 config.tools 归一化成 LLMToolSpec 列表。

    接受两种输入：
    - list[LLMToolSpec]（已构造好）
    - list[dict]：{name, description, parameters}
    其他形状忽略。
    """
    if not tools_raw or not isinstance(tools_raw, list):
        return []

    specs: list[LLMToolSpec] = []
    for item in tools_raw:
        if isinstance(item, LLMToolSpec):
            specs.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("function", {}).get("name")
        if not name:
            continue
        description = item.get("description") or item.get("function", {}).get("description", "")
        parameters = item.get("parameters") or item.get("function", {}).get("parameters") or {
            "type": "object",
            "properties": {},
        }
        specs.append(LLMToolSpec(
            name=str(name),
            description=str(description),
            parameters=parameters,
        ))
    return specs


async def _execute_one_tool(
    tool_executor: Any,
    name: str,
    raw_arguments: str,
) -> str:
    """执行单个 tool_call；未注册执行器或执行失败时返回错误文本回灌 LLM。"""
    if tool_executor is None:
        return f"[error] 工具未注册: {name}"

    args = _parse_arguments(raw_arguments)
    try:
        result = tool_executor(name, args)
        # 支持 async 函数 / 同步函数 / 协程
        if hasattr(result, "__await__"):
            result = await result
        return str(result)
    except Exception as exc:  # noqa: BLE001 - 工具失败不应中断主循环
        logger.warning("工具执行失败: %s err=%s", name, exc)
        return f"[error] {name}: {exc}"


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    except (json.JSONDecodeError, ValueError):
        return {"input": str(raw or "")}


def _accumulate_usage(aggregated: dict[str, int], resp: Any) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    aggregated["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
    aggregated["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
    aggregated["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)


def _to_str(value: Any) -> str:
    """把 config 字段解包成字符串：Expr 递归解包，其他类型 str()。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, TemplatedString):
        return value.template
    if isinstance(value, Literal):
        return _to_str(value.value)
    if isinstance(value, Expr):
        return str(value)
    return str(value)


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
