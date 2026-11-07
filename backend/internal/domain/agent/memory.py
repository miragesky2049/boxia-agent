"""智能体短期记忆的纯领域逻辑（0074 PRD F8，20261107）。

职责边界：只做"配置解析 + 窗口轮数/ token 预算截断"，不触仓储与框架——
组装点在应用层（ChatService 对 user 端 chat 通道统一拉历史后经 history 入参
注入画布/进程内两条通道），节点/通道消费本模块输出即可。

token 估算为自实现算法：项目暂无精确 tokenizer，中文约 1 字符 ≈ 1 token、
英文约 4 字符 ≈ 1 token，混合文本取 len//2+1 作近似（偏保守，宁可多算防
上下文超限）；P2 计划替换为 BPE 精确计量。截断顺序：先按窗口轮数取最近
若干条（1 轮 = 1 user + 1 assistant），再在预算内从最旧逐条丢弃，
绝不丢弃最新一条，保持时间正序。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# 与 settings.memory_max_turns 对齐：20261107 起该配置接线为本模块默认值来源
# （此前配置零消费方，见 PRD 台账 BUG-2 / F8.3）
DEFAULT_WINDOW_TURNS = 20
# 历史消息段默认预算（token，不含 system 与本轮输入）
DEFAULT_TOKEN_BUDGET = 6000

MIN_WINDOW_TURNS = 1
MAX_WINDOW_TURNS = 100
MIN_TOKEN_BUDGET = 500
MAX_TOKEN_BUDGET = 200000

STRATEGY_TRUNCATE = "truncate"
# summarize 属三期能力（PRD F8.4），此处显式识别但按 truncate 降级执行
STRATEGY_SUMMARIZE = "summarize"


def _to_bounded_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    """防御式取正整数：非法/越界一律回退默认值（与 _to_int 同口径的"非正即未配置"）。"""
    try:
        result = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    if result < min_value or result > max_value:
        return default
    return result


def parse_memory_config(raw: Any) -> dict[str, Any]:
    """解析画布 agent_loop 节点 config.memory → 归一化短期记忆配置。

    返回 {enabled, windowTurns, tokenBudget, strategy}；缺失/非法全部落默认值。
    strategy 传 summarize 时按 truncate 执行（显式降级，不静默支持未实现能力）。
    """
    short_term: dict[str, Any] = {}
    if isinstance(raw, dict) and isinstance(raw.get("shortTerm"), dict):
        short_term = raw["shortTerm"]
    strategy = str(short_term.get("strategy") or STRATEGY_TRUNCATE)
    if strategy != STRATEGY_SUMMARIZE:
        strategy = STRATEGY_TRUNCATE
    return {
        # 默认开启：agent 型应用"服务端自动记忆"是产品预期（PRD F1.3 默认配置）
        "enabled": bool(short_term.get("enabled", True)),
        "windowTurns": _to_bounded_int(
            short_term.get("windowTurns"), DEFAULT_WINDOW_TURNS, MIN_WINDOW_TURNS, MAX_WINDOW_TURNS
        ),
        "tokenBudget": _to_bounded_int(
            short_term.get("tokenBudget"), DEFAULT_TOKEN_BUDGET, MIN_TOKEN_BUDGET, MAX_TOKEN_BUDGET
        ),
        "strategy": STRATEGY_TRUNCATE,
    }


def estimate_tokens(text: str) -> int:
    """中英混合近似估算（算法见模块 docstring）。"""
    return len(text or "") // 2 + 1


def normalize_history_rows(rows: Iterable[Any]) -> list[dict[str, str]]:
    """把 message 行（dict 或带 role/content 属性的对象）转为 [{role, content}]。

    与迁移前 chat 通道过滤规则一致：只保留 user/assistant 且内容非空。
    """
    result: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            role = row.get("role")
            content = row.get("content")
        else:
            role = getattr(row, "role", None)
            content = getattr(row, "content", None)
        if role not in ("user", "assistant") or not content:
            continue
        result.append({"role": str(role), "content": str(content)})
    return result


def trim_history(
    messages: list[dict[str, str]],
    *,
    window_turns: int,
    token_budget: int,
) -> list[dict[str, str]]:
    """双限截断：窗口轮数（条数 = window_turns*2）+ token 预算，保持时间正序。"""
    if not messages:
        return []
    windowed = messages[-window_turns * 2:]
    total = sum(estimate_tokens(item["content"]) for item in windowed)
    # 从最旧丢弃；至少保留最新 1 条（否则多轮记忆失去意义）
    while len(windowed) > 1 and total > token_budget:
        total -= estimate_tokens(windowed[0]["content"])
        windowed = windowed[1:]
    return windowed
