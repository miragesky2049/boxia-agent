"""意图识别节点（coze type=22）。

把用户输入交给 LLM 分类到预定义意图，输出 classificationId（整数）并按该 ID
路由到对应出口；未命中任何意图时返回 0（其他）。

配置约定（config）：
- intents: [{id?: int, name: str, description?: str}]，id 缺省时按顺序 1..n
- mode: fast（极速）/ full（完整）；full 可拼接会话历史
- modleName / model: 模型 ID（与 LLM 节点保持一致，优先 coze 拼写 modleName）
- needHistory / historyLimit: full 模式下是否拼接会话历史

输出：
- classificationId: int
- classificationName: str
- query: 原始输入
- error: LLM 失败时的错误信息（不阻断流程，按「其他」路由）

路由：NodeResult.route = str(classificationId)，由 Compiler 的 conditional_edges 消费。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)

OTHER_INTENT_ID = 0
DEFAULT_HISTORY_LIMIT = 10

_JSON_ID_RE = re.compile(r'"classification_id"\s*:\s*(\d+)')
_NUMBER_RE = re.compile(r"^\s*(\d+)\s*$")


def _parse_intents(raw: Any) -> list[dict[str, Any]]:
    """规范化意图列表：保证 id 唯一，缺省按 1..n 编号。"""
    if not isinstance(raw, list):
        return []
    intents: list[dict[str, Any]] = []
    used: set[int] = set()
    next_id = 1
    for item in raw:
        if isinstance(item, str):
            name, description = item.strip(), ""
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("intent") or "").strip()
            description = str(item.get("description") or "")
        else:
            continue
        if not name:
            continue
        raw_id = item.get("id") if isinstance(item, dict) else None
        try:
            intent_id = int(raw_id or 0)
        except (TypeError, ValueError):
            intent_id = 0
        if intent_id <= 0 or intent_id in used:
            while next_id in used:
                next_id += 1
            intent_id = next_id
        used.add(intent_id)
        next_id = max(next_id, intent_id + 1)
        intents.append(
            {
                "id": intent_id,
                "name": name,
                "description": description,
            }
        )
    return intents


def _build_system_prompt(intents: list[dict[str, Any]]) -> str:
    lines = [
        "你是意图识别器。根据用户输入，从下列意图中选择最匹配的一项。",
        "可选意图：",
    ]
    for item in intents:
        suffix = f"：{item['description']}" if item["description"] else ""
        lines.append(f"- {item['id']}. {item['name']}{suffix}")
    lines.append(
        '如果没有匹配项，返回 0（其他）。只输出 JSON，不要解释：{"classification_id": <整数>}'
    )
    return "\n".join(lines)


def _extract_id(content: str, valid_ids: set[int]) -> int | None:
    text = (content or "").strip()
    if not text:
        return None
    match = _JSON_ID_RE.search(text) or _NUMBER_RE.match(text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if value in valid_ids or value == OTHER_INTENT_ID else None


def _match_by_keyword(query: str, intents: list[dict[str, Any]]) -> int | None:
    """无 LLM 时的兜底：意图名称出现在输入里即命中。"""
    text = (query or "").strip()
    if not text:
        return None
    for item in intents:
        if item["name"] and item["name"] in text:
            return int(item["id"])
    return None


class IntentNodeHandler(NodeHandler):
    """type=22: LLM 意图分类 + 动态出口。"""

    type_name = NodeType.INTENT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}
        intents = _parse_intents(config.get("intents"))
        query = ctx.inputs.get("query")
        if query in (None, ""):
            query = config.get("query")
        if query in (None, ""):
            query = ctx.env.system.get("USER_INPUT", "")
        query_text = str(query or "")

        if not intents:
            return NodeResult(
                outputs={
                    "classificationId": OTHER_INTENT_ID,
                    "classificationName": "其他",
                    "query": query_text,
                },
                route=str(OTHER_INTENT_ID),
            )

        valid_ids = {int(item["id"]) for item in intents}
        model_id = str(config.get("modleName") or config.get("model") or "")
        mode = str(config.get("mode") or "fast")
        need_history = bool(config.get("needHistory", mode == "full"))
        history_limit = int(config.get("historyLimit") or DEFAULT_HISTORY_LIMIT)

        error_message = ""
        classification_id: int | None = None

        if model_id and ctx.services.has("llm"):
            try:
                classification_id = await self._classify_with_llm(
                    ctx=ctx,
                    query=query_text,
                    intents=intents,
                    valid_ids=valid_ids,
                    model_id=model_id,
                    need_history=need_history,
                    history_limit=history_limit,
                )
            except Exception as exc:  # noqa: BLE001
                # 分类失败不中断流程：落到「其他」分支，并保留错误信息供排查
                logger.warning("意图识别失败，按其他处理: node=%s error=%s", ctx.node_id, exc)
                error_message = str(exc)
        else:
            classification_id = _match_by_keyword(query_text, intents)

        if classification_id is None:
            classification_id = OTHER_INTENT_ID

        matched = next(
            (item for item in intents if int(item["id"]) == classification_id),
            None,
        )
        outputs: dict[str, Any] = {
            "classificationId": classification_id,
            "classificationName": matched["name"] if matched else "其他",
            "query": query_text,
        }
        if error_message:
            outputs["error"] = error_message
        return NodeResult(outputs=outputs, route=str(classification_id))

    async def _classify_with_llm(
        self,
        *,
        ctx: NodeContext,
        query: str,
        intents: list[dict[str, Any]],
        valid_ids: set[int],
        model_id: str,
        need_history: bool,
        history_limit: int,
    ) -> int | None:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _build_system_prompt(intents)},
        ]
        if need_history and ctx.services.has("message_repo"):
            history = await self._load_history(ctx, history_limit)
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        response = await ctx.services.get("llm").chat(
            messages=messages,
            model=model_id,
            temperature=0.0,
        )
        return _extract_id(getattr(response, "content", "") or "", valid_ids)

    async def _load_history(
        self,
        ctx: NodeContext,
        limit: int,
    ) -> list[dict[str, str]]:
        conversation_id = ctx.env.conversation_id
        if conversation_id is None:
            return []
        try:
            messages = await ctx.services.get("message_repo").list_by_conversation(
                conversation_id,
                limit=limit,
            )
        except Exception:  # noqa: BLE001
            logger.exception("意图识别读取会话历史失败: node=%s", ctx.node_id)
            return []
        history: list[dict[str, str]] = []
        for message in messages:
            role = getattr(message, "role", "")
            if role in ("user", "assistant"):
                history.append({"role": role, "content": str(getattr(message, "content", ""))})
        return history


register_node_handler(IntentNodeHandler())
