"""M4-d T-d8 F19.3：JudgeSamplingService 单测（fake LLM + duck-type 仓储，先例抽取服务）。

契约：run 成功且有 Q/A 才判、source=runtime_sample 落库、幂等探测、关闭态零开销、
模型回退链 judgeModel→答题模型→settings 默认、judge usage 入 ledger、异常上抛给任务重试。
异步入口按项目惯例 asyncio.run 包装。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from internal.application.apps.judge_sampling_service import JudgeSamplingService


def _literal(value: object) -> dict:
    return {"value": {"type": "literal", "content": value}}


def _canvas_graph(judge_sampling: dict[str, Any] | None, model: str = "m-main") -> dict:
    inputs: dict[str, Any] = {"modleName": _literal(model)}
    if judge_sampling is not None:
        inputs["judgeSampling"] = _literal(judge_sampling)
    return {
        "nodes": [{"id": "loop_1", "type": "100", "data": {"inputs": inputs, "outputs": []}}],
        "edges": [],
    }


class _FakeJudgeLLM:
    def __init__(self, content: str = '{"score": 8, "passed": true, "critique": "好"}') -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *, messages: list[dict[str, Any]], **kwargs: Any):
        from internal.domain.llm.client import LLMResponse, LLMUsage

        self.calls.append({"messages": messages, **kwargs})
        return LLMResponse(
            content=self._content,
            usage=LLMUsage(prompt_tokens=11, completion_tokens=5, total_tokens=16),
        )


class _FakeModelService:
    def __init__(self, client: _FakeJudgeLLM, unknown_models: tuple[str, ...] = ()) -> None:
        self.client = client
        self.unknown = set(unknown_models)
        self.requested: list[str] = []

    def get_client_for_tenant(self, model_id: str, tenant_id: Any) -> _FakeJudgeLLM:
        from internal.application.errors import NotFoundError

        self.requested.append(model_id)
        if model_id in self.unknown:
            raise NotFoundError(f"模型未配置: {model_id}")
        return self.client


class _RunRepo:
    def __init__(self, run: dict | None) -> None:
        self._run = run

    def get_run(self, run_id: Any) -> dict | None:
        return self._run


class _MsgRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list_messages_by_run(self, run_id: Any) -> list[dict]:
        return self._rows


class _EvalRepo:
    def __init__(self, sampled: bool = False) -> None:
        self.sampled = sampled
        self.rows: list[dict] = []

    def has_runtime_sample(self, run_id: Any) -> bool:
        return self.sampled

    def insert_results(self, rows: list[dict]) -> None:
        self.rows.extend(rows)


class _UsageRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_usage(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _run(**overrides: Any) -> dict:
    run = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "workflow_id": uuid4(),
        "user_id": uuid4(),
        "execute_status": "success",
        "is_eval": False,
        "parent_run_id": None,
        "graph_snapshot": _canvas_graph({"enabled": True, "rate": 0.2, "judgeModel": "m-judge"}),
        "input": {"input": "北京天气"},
        "output": None,
    }
    run.update(overrides)
    return run


def _service(
    run: dict | None,
    messages: list[dict] | None = None,
    *,
    llm: _FakeJudgeLLM | None = None,
    eval_repo: _EvalRepo | None = None,
    default_model_id: str = "m-default",
    unknown_models: tuple[str, ...] = (),
) -> tuple[JudgeSamplingService, dict[str, Any]]:
    llm = llm or _FakeJudgeLLM()
    model_service = _FakeModelService(llm, unknown_models)
    usage_repo = _UsageRepo()
    eval_repo = eval_repo or _EvalRepo()
    msg_repo = _MsgRepo(
        messages
        if messages is not None
        else [
            {"role": "user", "content": "北京天气"},
            {"role": "assistant", "content": "晴，25 度"},
        ]
    )
    service = JudgeSamplingService(
        run_repo=_RunRepo(run),
        msg_repo=msg_repo,
        eval_repo=eval_repo,
        usage_repo=usage_repo,
        model_service=model_service,
        default_model_id=default_model_id,
    )
    return service, {
        "llm": llm,
        "model_service": model_service,
        "usage_repo": usage_repo,
        "eval_repo": eval_repo,
    }


def test_sample_writes_runtime_sample_row_and_ledger() -> None:
    run = _run()
    service, parts = _service(run)

    result = asyncio.run(service.sample_for_run(run["id"]))

    assert result == {"status": "pass", "score": 8}
    row = parts["eval_repo"].rows[0]
    assert row["source"] == "runtime_sample"
    assert row["run_id"] == run["id"]
    assert row["tenant_id"] == run["tenant_id"]
    assert row["status"] == "pass" and row["score"] == 8
    assert row["reason"] == "好"
    assert row["judge_usage"] == {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
    ledger = parts["usage_repo"].calls[0]
    assert ledger["node_id"] == "judge_sampling"
    assert ledger["model_id"] == "m-judge"
    assert ledger["run_id"] == run["id"] and ledger["total_tokens"] == 16
    # judgeModel 显式配置优先（回退链见 test_model_fallback_chain）
    assert parts["model_service"].requested == ["m-judge"]


def test_sample_fail_verdict_maps_to_fail_status() -> None:
    # 判定信模型给出的 passed 字段，不按分数线重推（采样键组无 passScore，F 决策）
    run = _run(graph_snapshot=_canvas_graph({"enabled": True, "rubric": "只评格式"}))
    llm = _FakeJudgeLLM('{"score": 8, "passed": false, "critique": "答非所问"}')
    service, parts = _service(run, llm=llm)

    result = asyncio.run(service.sample_for_run(run["id"]))

    assert result == {"status": "fail", "score": 8}
    assert parts["eval_repo"].rows[0]["status"] == "fail"
    # 自定义 rubric 透传给 judge 内核 system 段
    system_text = parts["llm"].calls[0]["messages"][0]["content"]
    assert "只评格式" in system_text


def test_sample_idempotent_skips_second_time() -> None:
    run = _run()
    service, parts = _service(run, eval_repo=_EvalRepo(sampled=True))

    assert asyncio.run(service.sample_for_run(run["id"])) is None
    assert parts["eval_repo"].rows == []
    assert parts["llm"].calls == []


def test_sample_skips_when_disabled_in_snapshot() -> None:
    run = _run(graph_snapshot=_canvas_graph({"enabled": False, "rate": 1.0}))
    service, parts = _service(run)

    assert asyncio.run(service.sample_for_run(run["id"])) is None
    assert parts["llm"].calls == []


def test_sample_skips_legacy_snapshot_without_key() -> None:
    run = _run(graph_snapshot=_canvas_graph(None))
    service, parts = _service(run)

    assert asyncio.run(service.sample_for_run(run["id"])) is None
    assert parts["llm"].calls == []


def test_sample_skips_without_assistant_answer() -> None:
    run = _run()
    service, parts = _service(run, messages=[{"role": "user", "content": "北京天气"}])

    assert asyncio.run(service.sample_for_run(run["id"])) is None
    assert parts["llm"].calls == []


@pytest.mark.parametrize("status", ["running", "interrupted", "error"])
def test_sample_skips_non_success_run(status: str) -> None:
    run = _run(execute_status=status)
    service, parts = _service(run)

    assert asyncio.run(service.sample_for_run(run["id"])) is None
    assert parts["llm"].calls == []


def test_sample_skips_eval_and_sub_runs() -> None:
    eval_run = _run(is_eval=True)
    service, parts = _service(eval_run)
    assert asyncio.run(service.sample_for_run(eval_run["id"])) is None

    sub_run = _run(parent_run_id=uuid4())
    service2, parts2 = _service(sub_run)
    assert asyncio.run(service2.sample_for_run(sub_run["id"])) is None
    assert parts["llm"].calls == [] and parts2["llm"].calls == []


def test_sample_model_fallback_chain() -> None:
    # judgeModel 空 → 画布答题模型
    run = _run(graph_snapshot=_canvas_graph({"enabled": True, "judgeModel": ""}, model="m-app"))
    service, parts = _service(run)
    asyncio.run(service.sample_for_run(run["id"]))
    assert parts["model_service"].requested == ["m-app"]

    # 答题模型也缺失 → settings 默认
    run2 = _run(graph_snapshot=_canvas_graph({"enabled": True}, model=""))
    service2, parts2 = _service(run2, default_model_id="m-default")
    asyncio.run(service2.sample_for_run(run2["id"]))
    assert parts2["model_service"].requested == ["m-default"]


def test_sample_invalid_judge_model_falls_back_not_zeroes_all() -> None:
    """批末 review P2-2：judgeModel 拼错/已删 → 按回退链降级继续判（F19.5：模型错配
    是配置质量问题，不应让整应用采样静默归零），并保留错配请求记录供排障。"""
    run = _run(
        graph_snapshot=_canvas_graph({"enabled": True, "judgeModel": "m-typo"}, model="m-app")
    )
    service, parts = _service(run, unknown_models=("m-typo",))

    result = asyncio.run(service.sample_for_run(run["id"]))

    assert result == {"status": "pass", "score": 8}
    assert parts["model_service"].requested == ["m-typo", "m-app"]
    assert parts["eval_repo"].rows[0]["source"] == "runtime_sample"


def test_sample_judge_exception_propagates_for_task_retry() -> None:
    class _BoomLLM:
        async def chat(self, **kwargs: Any) -> Any:
            raise ConnectionError("上游超时")

    run = _run()
    service, _ = _service(run, llm=_BoomLLM())  # type: ignore[arg-type]

    with pytest.raises(ConnectionError):
        asyncio.run(service.sample_for_run(run["id"]))


def test_sample_run_missing_returns_none() -> None:
    service, parts = _service(None)
    assert asyncio.run(service.sample_for_run(uuid4())) is None
    assert parts["llm"].calls == []
