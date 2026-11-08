"""M4-d PRD F19.1：LLM-as-judge 唯一内核（C5 同源约束）。

离线评估器（F18.4）、运行时质量门（F19.2）、线上采样（F19.3）三处消费共用本函数，
杜绝三份拼写漂移。输出契约：JSON 结构化 + temperature 0；解析失败重试 1 次后
按 passed=false 兜底（宁可误杀不可漏判，放行策略由消费方质量门按 U13 裁决决定）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from internal.domain.agent.prompt import JUDGE_RUBRIC_DEFAULT, JUDGE_SYSTEM_PROMPT
from internal.domain.llm.client import LLMClient, LLMUsage

logger = logging.getLogger(__name__)

# 兜底通过阈值：模型未输出 passed 字段时按此分推导。与 prompt.JUDGE_RUBRIC_DEFAULT
# 文案中的"7 及以上视为通过"保持一致；消费方自定义 rubric 改写阈值时 passed 通常
# 由模型直接给出，本常量仅在缺字段时生效。
DEFAULT_PASS_SCORE = 7

_MAX_SCORE = 10

# 评审输出可能无视 response_format 仍包 markdown 围栏，取第一段 JSON 体兜底解析
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class JudgeVerdict(BaseModel):
    """单次 judge 判定结果。"""

    score: int = 0
    passed: bool = False
    critique: str = ""
    # 被评模型名：透出到 eval_result / trace，供报告与看板归因
    model: str = ""
    # judge 自身调用（含重试）的 token 累计，F19.2 计入 run 预算
    usage: LLMUsage = Field(default_factory=LLMUsage)


def _extract_json_object(content: str) -> dict[str, Any]:
    """把模型输出解析为 JSON 对象；无法解析时抛 ValueError。"""
    text = content.strip()
    fenced = _FENCE_PATTERN.search(text)
    if fenced:
        text = fenced.group(1)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"judge 输出不是 JSON 对象: {type(parsed).__name__}")
    return parsed


def _normalize_passed(raw: Any, score: int) -> bool:
    """passed 字段显式归一（批末 review P2-3）：provider 未守 json schema 时模型常把
    布尔写成字符串，bool("false") 为真会反转判定，必须按词面解析；缺字段/不可解析值
    走 DEFAULT_PASS_SCORE 推导（与默认 rubric 文案一致）。"""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "yes"):
            return True
        if lowered in ("false", "no"):
            return False
    elif isinstance(raw, (int, float)):
        return bool(raw)
    return score >= DEFAULT_PASS_SCORE


def _to_verdict(payload: dict[str, Any], model: str, usage: LLMUsage) -> JudgeVerdict:
    raw_score = int(payload.get("score", 0))
    score = max(0, min(_MAX_SCORE, raw_score))
    passed = _normalize_passed(payload.get("passed"), score)
    return JudgeVerdict(
        score=score,
        passed=passed,
        critique=str(payload.get("critique") or ""),
        model=model,
        usage=usage,
    )


async def judge(
    llm: LLMClient,
    *,
    model: str,
    rubric: str,
    question: str,
    answer: str,
    context_refs: list[str] | None = None,
) -> JudgeVerdict:
    """按评分准则对回答打分。

    :param llm: judge 使用的模型客户端（judgeModel 解析由消费方完成，F19.5）。
    :param model: 被评/评分模型名，仅用于结果归因透出。
    :param rubric: 评分准则；空串回退内置三段默认模板。
    :param question: 本轮用户问题。
    :param answer: 待评的最终回答文本。
    :param context_refs: 事实性判断的参考材料（工具结果/检索片段），可为 None。
    :return: JudgeVerdict；连续两次解析失败时 score=0、passed=false、critique 说明失败。
    """
    system = JUDGE_SYSTEM_PROMPT.format(rubric=rubric.strip() or JUDGE_RUBRIC_DEFAULT)
    user_parts = [f"【问题】\n{question}", f"【回答】\n{answer}"]
    if context_refs:
        refs = "\n".join(f"- {ref}" for ref in context_refs)
        user_parts.append(f"【参考资料】\n{refs}")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    usage_total = LLMUsage()
    # 解析失败重试 1 次（F19.1）：第二次把"只输出 JSON"约束追加强化
    for attempt in range(2):
        response = await llm.chat(
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        usage_total = LLMUsage(
            prompt_tokens=usage_total.prompt_tokens + response.usage.prompt_tokens,
            completion_tokens=usage_total.completion_tokens + response.usage.completion_tokens,
            total_tokens=usage_total.total_tokens + response.usage.total_tokens,
        )
        try:
            payload = _extract_json_object(response.content)
        except (ValueError, json.JSONDecodeError):
            if attempt == 0:
                messages.append({"role": "user", "content": "上一条输出无法解析为 JSON 对象，请只输出规定的 JSON。"})
                continue
            logger.warning("judge 输出连续两次解析失败，model=%s", model)
            return JudgeVerdict(
                score=0,
                passed=False,
                critique="judge 输出解析失败，无法给出评分",
                model=model,
                usage=usage_total,
            )
        try:
            return _to_verdict(payload, model, usage_total)
        except (TypeError, ValueError, PydanticValidationError):
            # 字段类型异常与非法 JSON 同路径处理（重试→兜底）
            if attempt == 0:
                messages.append({"role": "user", "content": "上一条输出字段不符合要求，请只输出规定的 JSON。"})
                continue
            # 批末 review P3-3：payload 可能引用问答正文，日志截断防用户数据入日志
            logger.warning("judge 输出字段非法，model=%s payload=%s", model, str(payload)[:200])
            return JudgeVerdict(
                score=0,
                passed=False,
                critique="judge 输出解析失败，无法给出评分",
                model=model,
                usage=usage_total,
            )
    # 循环结构保证两次尝试内必 return；保留抛出以防未来改动破坏不变量
    raise RuntimeError("judge 重试循环异常退出")
