"""Query 改写器：结合对话历史生成独立 query + 多个同义变体。"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from internal.domain.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryRewriteResult:
    """改写结果：standalone 用于 rerank 主 query，variants 用于多 query 并行召回。"""

    standalone: str
    variants: list[str] = field(default_factory=list)

    @property
    def all_queries(self) -> list[str]:
        """用于 embedding 并行召回的全部 query 列表（去重、去空）。"""
        seen: set[str] = set()
        result: list[str] = []
        for q in [self.standalone, *self.variants]:
            cleaned = (q or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


class QueryRewriter(ABC):
    """Query 改写抽象：便于测试注入 / 替换规则实现。"""

    @abstractmethod
    async def rewrite(
        self,
        *,
        query: str,
        history: list[dict],
        variant_count: int = 3,
    ) -> QueryRewriteResult:
        """根据当前 query 与对话历史生成独立 query + N 个同义变体。"""


# 默认 prompt：要求 LLM 返回严格 JSON
_SYSTEM_PROMPT = """你是一个检索查询改写专家。给定用户当前问题和最近几轮对话历史，你需要：

1. 把当前问题改写成一个**独立、自包含**的检索 query（消解"它/这个/那/上面提到的"等指代）。
2. 生成 {variant_count} 个**不同表述角度**的同义改写变体（用于多 query 召回，提升召回率）。

输出严格 JSON，不要任何额外解释：
{{"standalone": "独立检索 query", "variants": ["变体1", "变体2", "变体3"]}}

要求：
- standalone 必须是完整的问题，能独立检索；
- variants 不要重复 standalone，每个变体用不同关键词或句式；
- 如果当前 query 已经是完整独立的问题，standalone 直接返回原文；
- 历史为空时，variants 仍需生成不同表述；
- 输出必须是合法 JSON，不要 markdown 代码块包裹。"""


class LLMQueryRewriter(QueryRewriter):
    """基于 LLM 的改写实现：复用 OpenAICompatLLMClient。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def rewrite(
        self,
        *,
        query: str,
        history: list[dict],
        variant_count: int = 3,
    ) -> QueryRewriteResult:
        """调用 LLM 生成改写结果；解析失败时兜底返回原始 query。"""
        if not query.strip():
            return QueryRewriteResult(standalone=query, variants=[])

        system = _SYSTEM_PROMPT.format(variant_count=variant_count)
        history_block = self._format_history(history)
        user_content = f"对话历史：\n{history_block}\n\n当前问题：{query}\n\n请输出 JSON："

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=300,
            )
        except Exception:  # noqa: BLE001 - 改写失败不阻断主流程
            logger.warning("query rewrite llm call failed", exc_info=True)
            return QueryRewriteResult(standalone=query, variants=[])

        parsed = self._parse_json(response.content)
        if not parsed:
            return QueryRewriteResult(standalone=query, variants=[])

        standalone = (parsed.get("standalone") or query).strip() or query
        variants_raw = parsed.get("variants") or []
        variants = [str(v).strip() for v in variants_raw if str(v).strip()][:variant_count]
        return QueryRewriteResult(standalone=standalone, variants=variants)

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        """把历史消息列表格式化为纯文本块；取最近 3 轮。"""
        if not history:
            return "（无历史）"
        recent = history[-6:]  # 3 轮 = 6 条
        lines: list[str] = []
        for item in recent:
            role = item.get("role") or ""
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            label = "用户" if role == "user" else "助手" if role == "assistant" else role
            lines.append(f"{label}: {content}")
        return "\n".join(lines) if lines else "（无历史）"

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        """从 LLM 输出中提取 JSON 对象；容忍 ```json 包裹与前后杂文本。"""
        if not content:
            return None
        # 去掉可能的 markdown 代码块
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
        # 尝试直接解析
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        # 兜底：抓第一个 { ... } 块
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.warning("query rewrite json parse failed content_len=%d", len(content or ""))
        return None
