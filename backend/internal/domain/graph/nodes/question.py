"""问答节点（coze type=18）：中途向用户提问并等待回答。

运行机制与人审节点一致，基于 langgraph interrupt：
1. 首次执行把 {question, options, answer_type} 作为中断 payload 抛出
2. 运行时持久化 state 并把问题推给前端
3. 用户回答后以 Command(resume={"answer": ...}) 续跑
4. 节点第二次执行时 interrupt() 返回回答，写入 outputs 供下游引用

回答类型（config.answerType）：
- direct：自由文本回答（默认）
- options：用户从预置选项中选择
- extract：用模型从用户回复中抽取结构化字段

输出对齐 coze：USER_RESPONSE（String）+ QUESTION_DATA（Array<Object>），
同时保留 question/answer 供历史画布引用。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import interrupt

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.graph.nodes.output import render_content

logger = logging.getLogger(__name__)

ANSWER_TYPE_DIRECT = "direct"
ANSWER_TYPE_OPTIONS = "options"
ANSWER_TYPE_EXTRACT = "extract"
_ANSWER_TYPES = {ANSWER_TYPE_DIRECT, ANSWER_TYPE_OPTIONS, ANSWER_TYPE_EXTRACT}


def _normalize_options(raw: Any) -> list[str]:
    """选项支持「每行一个」文本或数组，统一成字符串列表。"""
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _normalize_fields(raw: Any) -> list[str]:
    """抽取字段支持「每行一个」文本或数组；兼容 {name} 对象。"""
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if isinstance(raw, list):
        fields: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("field") or "").strip()
            else:
                name = str(item).strip()
            if name:
                fields.append(name)
        return fields
    return []


def _extract_answer(resume_value: Any) -> str:
    """从续跑值里取用户回答：兼容字符串与 {answer/content} 对象。"""
    if isinstance(resume_value, dict):
        value = resume_value.get("answer", resume_value.get("content", ""))
        return "" if value is None else str(value)
    return "" if resume_value is None else str(resume_value)


def _resolve_answer_type(config: dict[str, Any], options: list[str]) -> str:
    """回答类型缺省时按是否有选项推断，保持旧画布行为。"""
    raw = str(config.get("answerType") or "").strip()
    if raw in _ANSWER_TYPES:
        return raw
    return ANSWER_TYPE_OPTIONS if options else ANSWER_TYPE_DIRECT


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """解析模型返回的 JSON；容忍 ```json 代码块包裹。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class QuestionNodeHandler(NodeHandler):
    """type=18: 向用户提问并等待回答。"""

    type_name = NodeType.QUESTION.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}
        question = render_content(ctx, "question")
        raw_options = config.get("options")
        if ctx.evaluator is not None and ctx.eval_context is not None:
            raw_options = ctx.evaluator.resolve_config(raw_options, ctx.eval_context)
            if isinstance(raw_options, str) and "{{" in raw_options:
                raw_options = ctx.evaluator.template.eval_template(
                    raw_options,
                    ctx.eval_context,
                )
        options = _normalize_options(raw_options)
        answer_type = _resolve_answer_type(config, options)

        # 非选项模式下不把 options 传给前端，避免误渲染成选项卡
        payload_options = options if answer_type == ANSWER_TYPE_OPTIONS else []
        payload: dict[str, Any] = {
            "type": "question",
            "node_id": ctx.node_id,
            "node_title": str(config.get("title") or "问答"),
            "question": question,
            "options": payload_options,
            "answer_type": answer_type,
        }
        if answer_type == ANSWER_TYPE_EXTRACT:
            payload["extract_fields"] = _normalize_fields(config.get("extractFields"))

        resume_value = interrupt(payload)
        answer = _extract_answer(resume_value)

        outputs: dict[str, Any] = {
            "question": question,
            "answer": answer,
            "USER_RESPONSE": answer,
            "QUESTION_DATA": [{"content_type": "text", "content": answer}],
        }

        if answer_type == ANSWER_TYPE_EXTRACT:
            fields = _normalize_fields(config.get("extractFields"))
            if fields:
                extracted, error = await self._extract_fields(ctx, answer, fields)
                if extracted:
                    outputs["extracted"] = extracted
                if error:
                    outputs["error"] = error

        return NodeResult(outputs=outputs)

    async def _extract_fields(
        self,
        ctx: NodeContext,
        answer: str,
        fields: list[str],
    ) -> tuple[dict[str, Any], str]:
        """用模型把自由文本回答抽取成结构化字段。"""
        model = str(
            (ctx.config or {}).get("modleName") or (ctx.config or {}).get("modelName") or ""
        )
        if not model or not ctx.services.has("llm"):
            return {}, "未配置模型，无法从回复中提取字段"

        field_desc = "、".join(fields)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是信息抽取助手。请从用户回复中抽取指定字段，"
                    "只输出 JSON 对象，不要解释。缺失字段填 null。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"需要抽取的字段：{field_desc}\n"
                    f"用户回复：{answer}\n"
                    f"输出 JSON，键为字段名：{json.dumps(fields, ensure_ascii=False)}"
                ),
            },
        ]
        try:
            response = await ctx.services.get("llm").chat(
                messages=messages,
                model=model,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001 - 抽取失败不阻断主流程
            logger.warning("问答节点字段抽取失败: node=%s err=%s", ctx.node_id, exc)
            return {}, f"字段抽取失败: {exc}"

        parsed = _parse_json_object(getattr(response, "content", "") or "")
        if parsed is None:
            return {}, "字段抽取结果不是合法 JSON"
        return parsed, ""


register_node_handler(QuestionNodeHandler())
