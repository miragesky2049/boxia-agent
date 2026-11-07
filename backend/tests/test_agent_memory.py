"""0074 PRD F8：智能体短期记忆纯逻辑单测（domain/agent/memory）。"""

from __future__ import annotations

import pytest

from internal.domain.agent.memory import (
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_TURNS,
    STRATEGY_TRUNCATE,
    estimate_tokens,
    normalize_history_rows,
    parse_memory_config,
    trim_history,
)


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class TestParseMemoryConfig:
    def test_missing_config_falls_back_to_defaults_enabled(self) -> None:
        """默认开启记忆：agent 应用"服务端自动记忆"是产品预期（F1.3）。"""
        for raw in (None, {}, "非法", [], {"shortTerm": "非法"}):
            parsed = parse_memory_config(raw)
            assert parsed == {
                "enabled": True,
                "windowTurns": DEFAULT_WINDOW_TURNS,
                "tokenBudget": DEFAULT_TOKEN_BUDGET,
                "strategy": STRATEGY_TRUNCATE,
            }

    def test_explicit_values_and_bounds(self) -> None:
        parsed = parse_memory_config({"shortTerm": {"enabled": False, "windowTurns": 5, "tokenBudget": 1000}})
        assert parsed["enabled"] is False
        assert parsed["windowTurns"] == 5
        assert parsed["tokenBudget"] == 1000
        # 越界回退默认
        parsed = parse_memory_config({"shortTerm": {"windowTurns": 0, "tokenBudget": 10}})
        assert parsed["windowTurns"] == DEFAULT_WINDOW_TURNS
        assert parsed["tokenBudget"] == DEFAULT_TOKEN_BUDGET

    def test_summarize_degrades_to_truncate(self) -> None:
        """summarize 属三期能力：显式识别但降级执行，不静默假支持。"""
        parsed = parse_memory_config({"shortTerm": {"strategy": "summarize"}})
        assert parsed["strategy"] == STRATEGY_TRUNCATE


class TestNormalizeHistoryRows:
    def test_dict_rows_filter_invalid(self) -> None:
        rows = [
            _msg("user", "早"),
            _msg("assistant", ""),
            _msg("system", "过滤"),
            _msg("tool", "过滤"),
            {"role": "assistant", "content": "你好"},
        ]
        assert normalize_history_rows(rows) == [_msg("user", "早"), _msg("assistant", "你好")]

    def test_object_rows_supported(self) -> None:
        class _Row:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        rows = [_Row("user", "a"), _Row("assistant", None), _Row("assistant", "b")]
        assert normalize_history_rows(rows) == [_msg("user", "a"), _msg("assistant", "b")]


class TestTrimHistory:
    def test_empty(self) -> None:
        assert trim_history([], window_turns=5, token_budget=100) == []

    def test_window_limits_to_latest_turns(self) -> None:
        messages = [_msg("user", f"q{i}") for i in range(10)]
        trimmed = trim_history(messages, window_turns=2, token_budget=99999)
        assert trimmed == messages[-4:]

    def test_token_budget_drops_oldest_first(self) -> None:
        messages = [
            _msg("user", "x" * 2000),
            _msg("assistant", "y" * 10),
            _msg("user", "z" * 10),
        ]
        budget = estimate_tokens("y" * 10) + estimate_tokens("z" * 10)
        trimmed = trim_history(messages, window_turns=20, token_budget=budget)
        assert trimmed == messages[1:]

    def test_latest_message_always_kept(self) -> None:
        """单条超预算也不能清空历史——保最新一条，保持时间正序。"""
        messages = [_msg("user", "x" * 4000)]
        assert trim_history(messages, window_turns=1, token_budget=1) == messages


@pytest.mark.parametrize("text", ["", "中文测试", "abcdefgh"])
def test_estimate_tokens_positive_and_monotonic(text: str) -> None:
    assert estimate_tokens(text) >= 1
    assert estimate_tokens(text + "加长内容") > estimate_tokens(text)
