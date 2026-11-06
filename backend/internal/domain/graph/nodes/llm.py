"""LLM 节点：调用大模型，支持 ReAct 工具调用循环。

config 约定（来自 coze llmParam 压平后的结构）：
- modleName: 模型显示名（注意 coze 拼写是 modleName，不是 modelName）
- temperature / maxTokens / responseFormat: 采样参数
- prompt: 用户提示词模板，支持 {{当前节点.input}} 和 {{上游节点.output.field}} 引用
- systemPrompt: 系统提示词，同上
- tools: 可选，向模型暴露的工具 schema 列表（OpenAI tools 数组项）
  每个元素是 dict：{name, description, parameters: JSON-Schema}
- maxToolRounds: 可选，ReAct 最大轮次（默认 5，防死循环）
- needHistory: 可选，bool。为 true 时从 message_repo 拉最近 N 条历史 user/assistant
  消息拼进 messages（T6 记忆开关）。
- historyLimit: 可选，int。needHistory=true 时拉取条数，默认 10。

求值顺序：
1. 先把 prompt 里的 {{input}} 占位符替换成当前节点的 inputs["input"]（coze 约定）
2. 再用 ExpressionEvaluator 求值 {{node.output.field}} 这类模板引用

工具执行：通过 ctx.services.get("tool_executor") 拿执行器；
    tool_executor(name: str, arguments: dict) -> str，返回值文本回灌给 LLM。
    执行白名单 = config.tools 声明的工具名：模型调用未声明工具直接拒绝回灌，
    不触达执行器（防越权使用租户全量工具目录）；未注册执行器时回灌 "[error] 工具未注册"。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.domain.agent.react import (
    accumulate_usage,
    build_tool_specs,
    run_react_loop,
)
from internal.domain.canvas.expression import Expr, Literal, TemplatedString
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.llm.client import LLMToolSpec

logger = logging.getLogger(__name__)

# ReAct 最大轮次：防止 LLM 陷入死循环
DEFAULT_MAX_TOOL_ROUNDS = 5
# needHistory 默认拉取条数
DEFAULT_HISTORY_LIMIT = 10


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
        need_history = _to_bool(_pick("needHistory"), default=False)
        history_limit = _to_int(_pick("historyLimit")) or DEFAULT_HISTORY_LIMIT
        stream_enabled = _to_bool(_pick("stream"), default=True)

        user_input = ctx.inputs.get("input")

        # 第一步：替换 {{input}} 占位符（coze 约定的当前节点输入引用）
        prompt_text = prompt_template.replace("{{input}}", str(user_input or ""))
        system_prompt = system_prompt_template.replace("{{input}}", str(user_input or ""))

        # 第二步：用 evaluator 对 {{node.output.field}} 这类模板引用做插值
        # prompt 来自前端简化格式时是纯字符串，resolve_config 对字符串是空操作，
        # 必须走 eval_template 才会替换 {{...}}。
        if ctx.evaluator is not None and ctx.eval_context is not None:
            template = ctx.evaluator.template
            prompt_text = template.eval_template(prompt_text, ctx.eval_context)
            system_prompt = template.eval_template(system_prompt, ctx.eval_context)

        # 未注入 llm 服务时返回 stub，保持开发态可跑
        if not ctx.services.has("llm"):
            return NodeResult(outputs={
                "output": f"[LLM stub] model={model_id} input={str(prompt_text)[:80]}",
            })

        llm_service = ctx.services.get("llm")
        # 20260731 双轨合并：工具 schema 归一化收敛到 react.build_tool_specs，
        # 声明名集合即内核执行白名单
        tool_specs = build_tool_specs(tools_raw)
        tool_executor = ctx.services.get("tool_executor") if ctx.services.has("tool_executor") else None

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # T6 记忆开关：needHistory=true 时把会话历史拼进 messages（system 之后、当前 user 之前）
        if need_history:
            history_messages = await _load_conversation_history(
                ctx=ctx,
                history_limit=history_limit,
            )
            messages.extend(history_messages)

        # T18 多模态：从 inputs["images"] 或 config["images"] 取图片 URL 列表，
        # 把 user content 包装成 OpenAI multi-modal content part 数组
        images = _extract_images(ctx, config)
        user_content: Any = str(prompt_text)
        if images:
            user_content = _build_multimodal_content(str(prompt_text), images)
        messages.append({"role": "user", "content": user_content})

        temperature = _to_float(temperature_raw, 0.7)
        max_tokens = _to_int(max_tokens_raw)
        response_format = (
            {"type": "json_object"}
            if str(response_format_raw).lower() in ("2", "json", "json_object")
            else None
        )

        # ReAct 循环：调 LLM → 若返回 tool_calls 则执行 → 把结果回灌 → 再调
        aggregated_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        final_content = ""
        final_reasoning = ""
        tool_call_log: list[dict[str, Any]] = []

        try:
            # 走流式路径：开启流式 + 无 tools + 有 SSE emit_event 通道时，逐 token 推 llm_token 事件
            if stream_enabled and not tool_specs and ctx.emit_event is not None:
                final_content, final_reasoning = await _run_streaming(
                    llm_service=llm_service,
                    ctx=ctx,
                    messages=messages,
                    model_id=model_id,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    aggregated_usage=aggregated_usage,
                )
            else:
                # 20260731 双轨合并：非流式分支收敛到 react.run_react_loop 内核，
                # 白名单/参数解析/异常转文本均由内核统一承担
                final_content, final_reasoning = await _run_react_collect(
                    llm_service=llm_service,
                    messages=messages,
                    tool_specs=tool_specs,
                    tool_executor=tool_executor,
                    max_rounds=max_rounds,
                    chat_kwargs={
                        "model": model_id,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": response_format,
                    },
                    aggregated_usage=aggregated_usage,
                    tool_call_log=tool_call_log,
                )
        except Exception as exc:
            logger.exception("LLM 调用失败: node=%s", ctx.node_id)
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc

        outputs: dict[str, Any] = {
            "output": final_content,
            "model": model_id,
        }
        if final_reasoning:
            outputs["reasoning_content"] = final_reasoning
        if tool_call_log:
            outputs["tool_calls"] = tool_call_log

        return NodeResult(outputs=outputs, usage=aggregated_usage)


async def _run_react_collect(
    *,
    llm_service: Any,
    messages: list[dict[str, Any]],
    tool_specs: list[LLMToolSpec],
    tool_executor: Any,
    max_rounds: int,
    chat_kwargs: dict[str, Any],
    aggregated_usage: dict[str, int],
    tool_call_log: list[dict[str, Any]],
) -> tuple[str, str]:
    """消费共享 ReAct 内核事件流，收集 LLM 节点输出所需的 (content, reasoning)。

    - usage 在 llm_end 逐轮累计：即使后续轮 LLM 异常，已消耗 token 不丢；
    - tool_call_log 保持迁移前形态：{name, arguments(原始字符串), observation}；
    - 轮次耗尽沿用原节点文案，避免画布输出回归。
    """
    final_content = ""
    final_reasoning = ""
    async for event in run_react_loop(
        llm=llm_service,
        messages=messages,
        tool_specs=tool_specs,
        tool_executor=tool_executor,
        max_rounds=max_rounds,
        chat_kwargs=chat_kwargs,
        max_rounds_message="（达到最大工具调用轮次，已停止）",
    ):
        payload = event.payload
        if event.kind == "llm_end":
            accumulate_usage(aggregated_usage, payload["usage"])
        elif event.kind == "tool_end":
            tool_call_log.append({
                "name": payload["name"],
                "arguments": payload["arguments_raw"],
                "observation": payload["observation"],
            })
        elif event.kind == "result":
            final_content = payload["content"]
            final_reasoning = payload["reasoning_content"]
    return final_content, final_reasoning


def _accumulate_usage(aggregated: dict[str, int], resp: Any) -> None:
    """累计一次响应/chunk 的 usage；实现收敛到 react.accumulate_usage。"""
    accumulate_usage(aggregated, getattr(resp, "usage", None))


async def _run_streaming(
    *,
    llm_service: Any,
    ctx: NodeContext,
    messages: list[dict[str, Any]],
    model_id: str,
    temperature: float,
    max_tokens: int | None,
    response_format: dict[str, Any] | None,
    aggregated_usage: dict[str, int],
) -> tuple[str, str]:
    """流式 LLM 调用：逐 chunk emit llm_token 事件，聚合完整 content / reasoning 返回。

    仅用于无 tools 的纯生成场景。stream 结束时若服务端返回 usage，回灌到 aggregated_usage。
    """
    assert ctx.emit_event is not None  # 调用方已保证

    chunks: list[str] = []
    reasoning_chunks: list[str] = []
    stream_kwargs: dict[str, Any] = {
        "messages": messages,
        "model": model_id,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": response_format,
    }

    stream = llm_service.chat_stream(**stream_kwargs)
    async for chunk in stream:
        delta = getattr(chunk, "content", "") or ""
        if delta:
            chunks.append(delta)
            await ctx.emit_event("llm_token", {
                "node_id": ctx.node_id,
                "delta": delta,
            })
        reasoning_delta = getattr(chunk, "reasoning_content", "") or ""
        if reasoning_delta:
            reasoning_chunks.append(reasoning_delta)
        # 收尾 chunk 带 usage（content 为空）
        _accumulate_usage(aggregated_usage, chunk)

    return "".join(chunks), "".join(reasoning_chunks)


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


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off", ""):
            return False
    return default


async def _load_conversation_history(
    *,
    ctx: NodeContext,
    history_limit: int,
) -> list[dict[str, Any]]:
    """T6 记忆开关：从 message_repo 拉最近 N 条历史 user/assistant 消息。

    conversation_id 来源优先级：
      1. ctx.inputs["conversation_id"]（通常由上游 CreateConversation / QueryConversationList 节点给出）
      2. ctx.config["conversation_id"]（静态配置，调试用）

    任一来源缺失或 message_repo 未注册时，静默返回空列表——LLM 节点退化为单轮对话，
    不抛错打断主流程。
    """
    if not ctx.services.has("message_repo"):
        return []

    raw_conv_id = ctx.inputs.get("conversation_id") or ctx.config.get("conversation_id")
    if not raw_conv_id:
        return []

    try:
        conv_id = UUID(str(raw_conv_id))
    except (ValueError, TypeError):
        logger.info("LLM needHistory 跳过：conversation_id 不是合法 UUID: %r", raw_conv_id)
        return []

    repo = ctx.services.get("message_repo")
    try:
        rows = await repo.list_by_conversation(conv_id, limit=history_limit)
    except Exception:  # noqa: BLE001 - 拉历史失败不应阻断主流程
        logger.exception("LLM needHistory 拉历史失败: conv_id=%s", conv_id)
        return []

    history: list[dict[str, Any]] = []
    for msg in rows:
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        if role not in ("user", "assistant"):
            continue
        if not content:
            continue
        history.append({"role": role, "content": content})
    return history


register_node_handler(LLMNodeHandler())


# ---------- T18 多模态 helpers ----------
def _extract_images(ctx: NodeContext, config: dict) -> list[str]:
    """从 inputs / config 中提取图片 URL 列表。

    支持两种来源：
    - ctx.inputs["images"]：上游节点（如 START 上传附件）传入的图片列表
    - config["images"]：节点静态配置的图片 URL 列表（调试用）

    输入形态：
    - list[str]：直接使用
    - str：逗号分隔的 URL（前端上传组件传逗号拼接），拆分为列表
    非字符串元素直接忽略。
    """
    raw = ctx.inputs.get("images")
    if raw is None:
        raw = config.get("images")
    if raw is None:
        return []
    if isinstance(raw, str):
        # 前端把多图拼成 "url1,url2,data:..." 形式；逗号分隔
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, (str,)) and str(x).strip()]


def _build_multimodal_content(text: str, images: list[str]) -> list[dict[str, Any]]:
    """把纯文本 + 图片 URL 列表组装成 OpenAI multi-modal content part 数组。"""
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for url in images:
        parts.append({
            "type": "image_url",
            "image_url": {"url": url},
        })
    return parts
