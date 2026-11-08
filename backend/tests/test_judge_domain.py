"""M4-d T-d1：judge 内核（PRD F19.1）+ ModelService judgeModel 解析（F19.5）。

契约要点：JSON 结构化输出 + temperature 0；解析失败重试 1 次后按 passed=false；
默认 rubric（相关性/事实性/无害性）可被配置覆盖；judgeModel 错配仅 warning 回退。
"""

from __future__ import annotations

import asyncio
from typing import Any

from internal.application.apps.model_service import ModelService
from internal.domain.agent.judge import JudgeVerdict, judge
from internal.domain.llm.client import LLMResponse, LLMUsage


class _FakeLLM:
    """按脚本顺序吐出 content 的假 LLM 客户端，记录每次 chat 入参。"""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *, messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any) -> LLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        content = self._contents.pop(0) if self._contents else "not-a-json"
        return LLMResponse(
            content=content,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def _run(llm: _FakeLLM, **overrides: Any) -> JudgeVerdict:
    params: dict[str, Any] = {
        "model": "deepseek-chat",
        "rubric": "",
        "question": "北京天气怎么样？",
        "answer": "多云，18℃。",
        "context_refs": None,
    }
    params.update(overrides)
    return asyncio.run(judge(llm, **params))  # type: ignore[arg-type]


def test_judge_parses_structured_verdict() -> None:
    llm = _FakeLLM(['{"score": 8, "passed": true, "critique": "基本准确"}'])
    verdict = _run(llm)
    assert verdict.score == 8
    assert verdict.passed is True
    assert verdict.critique == "基本准确"
    assert verdict.model == "deepseek-chat"
    call = llm.calls[0]
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}
    joined = str(call["messages"])
    assert "北京天气怎么样？" in joined and "多云，18℃。" in joined


def test_judge_clamps_score_range() -> None:
    assert _run(_FakeLLM(['{"score": 12, "passed": true}'])).score == 10
    assert _run(_FakeLLM(['{"score": -3, "passed": false}'])).score == 0


def test_judge_tolerates_markdown_fence() -> None:
    verdict = _run(_FakeLLM(['```json\n{"score": 6, "passed": false, "critique": "略偏"}\n```']))
    assert verdict.score == 6
    assert verdict.passed is False


def test_judge_passes_default_threshold_when_field_missing() -> None:
    # 模型漏写 passed 时按默认通过分 7 推导（rubric 模板内已声明阈值，此为兜底）
    assert _run(_FakeLLM(['{"score": 7}'])).passed is True
    assert _run(_FakeLLM(['{"score": 6}'])).passed is False


def test_judge_normalizes_string_boolean_passed() -> None:
    """批末 review P2-3：provider 未守 json schema 时模型常输出字符串布尔；
    bool("false") 为真会反转判定，必须显式解析而非真值化。"""
    assert _run(_FakeLLM(['{"score": 8, "passed": "false"}'])).passed is False
    assert _run(_FakeLLM(['{"score": 8, "passed": "true"}'])).passed is True
    assert _run(_FakeLLM(['{"score": 3, "passed": "no"}'])).passed is False
    # 无法解析的值按缺字段处理：走默认通过分推导
    assert _run(_FakeLLM(['{"score": 8, "passed": "maybe"}'])).passed is True
    assert _run(_FakeLLM(['{"score": 8, "passed": null}'])).passed is True
    assert _run(_FakeLLM(['{"score": 6, "passed": null}'])).passed is False


def test_judge_retries_once_then_succeeds() -> None:
    llm = _FakeLLM(["模型跑题输出的自然语言", '{"score": 9, "passed": true}'])
    verdict = _run(llm)
    assert verdict.score == 9 and verdict.passed is True
    assert len(llm.calls) == 2
    # 重试的 usage 需累计（F19.2 judge 调用计入 token 预算）
    assert verdict.usage.total_tokens == 30


def test_judge_fail_close_after_retry_exhausted() -> None:
    verdict = _run(_FakeLLM(["坏输出1", "坏输出2"]))
    assert verdict.score == 0
    assert verdict.passed is False
    assert "解析" in verdict.critique


def test_judge_default_rubric_covers_three_sections() -> None:
    llm = _FakeLLM(['{"score": 8, "passed": true}'])
    _run(llm)
    system_text = str(llm.calls[0]["messages"][0])
    for keyword in ("相关性", "事实性", "无害性"):
        assert keyword in system_text


def test_judge_custom_rubric_overrides_default() -> None:
    llm = _FakeLLM(['{"score": 8, "passed": true}'])
    _run(llm, rubric="只评幽默感，通过分 5")
    system_text = str(llm.calls[0]["messages"][0])
    assert "幽默感" in system_text and "相关性" not in system_text


def test_judge_context_refs_injected_only_when_present() -> None:
    llm = _FakeLLM(['{"score": 8, "passed": true}'])
    _run(llm, context_refs=["北京今日多云，18℃（气象接口）"])
    user_text = str(llm.calls[0]["messages"][1])
    assert "气象接口" in user_text
    llm2 = _FakeLLM(['{"score": 8, "passed": true}'])
    _run(llm2)
    assert "参考资料" not in str(llm2.calls[0]["messages"][1])


class _FakeModelRepo:
    def __init__(self, resolved: dict[str, Any] | None) -> None:
        self._resolved = resolved

    def resolve_model(self, model_id: str) -> dict[str, Any] | None:
        return self._resolved

    def resolve_model_for_tenant(self, model_id: str, tenant_id: Any) -> dict[str, Any] | None:
        return self._resolved


def test_resolve_judge_client_empty_id_returns_default() -> None:
    default = _FakeLLM([])
    service = ModelService(_FakeModelRepo(None))  # type: ignore[arg-type]
    assert service.resolve_judge_client("", default) is default  # type: ignore[arg-type]


def test_resolve_judge_client_unknown_model_warns_and_falls_back(monkeypatch: Any) -> None:
    # 项目 setup_logging 会替换 root handlers，caplog 不可用；直接捕获 warning 调用
    from internal.application.apps import model_service as ms_module

    warnings: list[str] = []
    monkeypatch.setattr(
        ms_module.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    default = _FakeLLM([])
    service = ModelService(_FakeModelRepo(None))  # type: ignore[arg-type]
    client = service.resolve_judge_client("judge-model-unknown-xyz", default)  # type: ignore[arg-type]
    assert client is default
    assert any("judge-model-unknown-xyz" in text for text in warnings)


def test_resolve_judge_client_resolves_catalog_model() -> None:
    default = _FakeLLM([])
    resolved = {"base_url": "https://example.invalid/v1", "api_key": "sk-test"}
    service = ModelService(_FakeModelRepo(resolved))  # type: ignore[arg-type]
    client = service.resolve_judge_client("deepseek-judge", default)  # type: ignore[arg-type]
    assert client is not default
