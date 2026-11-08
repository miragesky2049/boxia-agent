"""M4-d T-d3：EvalRunService 批任务单测（执行计划口径：Fake runner 三例 + 扩展）。

覆盖：批全过、单 case 异常不中断、进度单调、judge/rule 混合评分均值、
工具轨迹断言、eval_run.usage 汇总、投递降级（broker 不可达不影响发起）。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.eval_run_service import EvalRunService
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository


class _FakeRunner:
    """GraphRuntime 替身：invoke 返回预置 output；error 标记时抛异常。

    对齐 GraphRuntime.ensure_run 语义：非 error 构造时先落一行 run（eval_result.run_id
    有外键，报告跳转详情依赖该链路）；error 行按 T-d3 约定 run_id 置 NULL。
    """

    def __init__(self, uow, scope, output: dict[str, Any] | None = None, *, error: bool = False) -> None:
        self.run_id = uuid4()
        self._output = output or {}
        self._error = error
        if not error:
            tenant_id, app_id = scope
            RunRepository(uow.session).insert_run(
                run_id=self.run_id, tenant_id=tenant_id, workflow_id=app_id,
                graph_snapshot={"nodes": []}, input_data={"message": "fake"},
                thread_id=f"fake-{self.run_id}",
            )

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self._error:
            raise RuntimeError("图执行炸了")
        return self._output


class _FakeJudgeLLM:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *, messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any):
        from internal.domain.llm.client import LLMResponse, LLMUsage

        self.calls.append({"messages": messages, **kwargs})
        return LLMResponse(
            content=self._content,
            usage=LLMUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10),
        )


@pytest.fixture()
def uow():
    unit = SqlAlchemyUnitOfWork()
    unit.apply_scope((), apply_role_filter=False)
    try:
        yield unit
    finally:
        unit.close()


@pytest.fixture()
def scope(uow):
    code = f"ers-{uuid4().hex[:8]}"
    tenant = uow.tenants.create({"code": code, "name": f"批跑租户{code}"})
    app_id = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '批跑应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": app_id},
    )
    uow.commit()
    return tenant.id, app_id


def _service(
    uow,
    runners: dict[str, _FakeRunner],
    judge_llm: _FakeJudgeLLM | None = None,
    progress_log: list[dict] | None = None,
    judge_llm_factory: Any = None,
) -> EvalRunService:
    eval_repo = EvalRepository(uow.session)
    if progress_log is not None:
        class _RecordingEvalRepo(EvalRepository):
            def update_eval_run(self, run_id, **kwargs):  # noqa: ANN001, ANN101
                if kwargs.get("progress") is not None:
                    progress_log.append(dict(kwargs["progress"]))
                return super().update_eval_run(run_id, **kwargs)

        eval_repo = _RecordingEvalRepo(uow.session)

    async def _factory(case, tenant_id, application_id, graph_version):
        return runners[str(case["id"])]

    return EvalRunService(
        eval_repo=eval_repo,
        run_repo=RunRepository(uow.session),
        runtime_factory=_factory,
        judge_llm_factory=judge_llm_factory or (lambda model_id="": judge_llm),
    )


def _seed(uow, scope, cases: list[dict], evaluators: list[dict], graph_version: int = 2):
    tenant_id, app_id = scope
    repo = EvalRepository(uow.session)
    ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
    case_ids = []
    for payload in cases:
        created = repo.add_case(
            tenant_id=tenant_id,
            dataset_id=ds["id"],
            input_data=payload["input"],
            expected=payload.get("expected"),
            expected_tool_calls=payload.get("expected_tool_calls"),
        )
        case_ids.append(created)
    evaluator_ids = [
        repo.create_evaluator(
            tenant_id=tenant_id, name=ev["name"], type_=ev["type"], config=ev["config"]
        )
        for ev in evaluators
    ]
    run_id = uuid4()
    repo.insert_eval_run(
        run_id=run_id,
        tenant_id=tenant_id,
        application_id=app_id,
        graph_version=graph_version,
        dataset_id=ds["id"],
        evaluator_ids=[str(e["id"]) for e in evaluator_ids],
    )
    uow.commit()
    return repo, run_id, case_ids


def _results(uow, tenant_id, run_id):
    return EvalRepository(uow.session).list_results(tenant_id, run_id)


def test_full_pass_batch(uow, scope) -> None:
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}],
        [{"name": "包含a", "type": "rule", "config": {"contains": "结果"}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果ok"}) for c in cases}
    service = _service(uow, runners)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    done = repo.get_eval_run(scope[0], run_id)
    assert done["status"] == "completed"
    assert done["progress"] == {"total": 2, "done": 2, "passed": 2, "failed": 0, "errored": 0}
    rows = _results(uow, scope[0], run_id)
    assert all(r["status"] == "pass" and r["source"] == "eval_run" for r in rows)
    assert rows[0]["score"] == 10  # rule 通过记 10 分制（与 judge 同尺取均值）


def test_case_error_does_not_abort_batch(uow, scope) -> None:
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}, {"input": {"message": "c"}}],
        [{"name": "包含", "type": "rule", "config": {"contains": "结果"}}],
    )
    runners = {
        str(cases[0]["id"]): _FakeRunner(uow, scope, {"output": "结果1"}),
        str(cases[1]["id"]): _FakeRunner(uow, scope, error=True),
        str(cases[2]["id"]): _FakeRunner(uow, scope, {"output": "不符"}),
    }
    service = _service(uow, runners)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    done = repo.get_eval_run(scope[0], run_id)
    assert done["status"] == "completed"
    assert done["progress"] == {"total": 3, "done": 3, "passed": 1, "failed": 1, "errored": 1}
    rows = {r["reason"] for r in _results(uow, scope[0], run_id)}
    assert any("图执行炸了" in reason for reason in rows)


def test_progress_monotonic(uow, scope) -> None:
    _, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}, {"input": {"message": "c"}}],
        [{"name": "包含", "type": "rule", "config": {"contains": "结果"}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果"}) for c in cases}
    progress_log: list[dict] = []
    service = _service(uow, runners, progress_log=progress_log)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()
    dones = [p["done"] for p in progress_log]
    assert dones == sorted(dones)
    assert dones[-1] == 3


def test_mixed_rule_and_judge_averages_scores(uow, scope) -> None:
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}, "expected": "参考答案"}],
        [
            {"name": "包含", "type": "rule", "config": {"contains": "结果"}},
            {"name": "裁判", "type": "llm_judge", "config": {"passScore": 7, "rubric": "评事实性"}},
        ],
    )
    judge_llm = _FakeJudgeLLM('{"score": 8, "passed": true, "critique": "轻微瑕疵"}')
    runners = {str(cases[0]["id"]): _FakeRunner(uow, scope, {"output": "结果ok"})}
    service = _service(uow, runners, judge_llm=judge_llm)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    row = _results(uow, scope[0], run_id)[0]
    assert row["status"] == "pass"
    assert row["score"] == 9  # rule 10 与 judge 8 均值
    assert row["judge_usage"]["total_tokens"] == 10
    done = repo.get_eval_run(scope[0], run_id)
    assert done["usage"]["total_tokens"] == 10


def test_judge_not_pass_flips_case(uow, scope) -> None:
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}],
        [{"name": "裁判", "type": "llm_judge", "config": {"passScore": 7}}],
    )
    judge_llm = _FakeJudgeLLM('{"score": 4, "passed": false, "critique": "事实错误"}')
    runners = {str(cases[0]["id"]): _FakeRunner(uow, scope, {"output": "错答"})}
    service = _service(uow, runners, judge_llm=judge_llm)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    row = _results(uow, scope[0], run_id)[0]
    assert row["status"] == "fail" and row["score"] == 4
    assert "事实错误" in row["reason"]


def test_tool_trace_assertions(uow, scope) -> None:
    _, run_id, cases = _seed(
        uow,
        scope,
        [
            {
                "input": {"message": "a"},
                "expected_tool_calls": {"must_call": ["lookup_city"], "must_not_call": ["send_email"]},
            }
        ],
        [{"name": "恒过", "type": "rule", "config": {}}],
    )
    runners = {
        str(cases[0]["id"]): _FakeRunner(
            uow, scope, {"output": "结果", "tool_traces": [{"name": "lookup_city"}]}
        )
    }
    service = _service(uow, runners)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()
    assert _results(uow, scope[0], run_id)[0]["status"] == "pass"

    # must_call 未命中 → fail
    _, run_id2, cases2 = _seed(
        uow,
        scope,
        [
            {
                "input": {"message": "b"},
                "expected_tool_calls": {"must_call": ["send_email"]},
            }
        ],
        [{"name": "恒过", "type": "rule", "config": {}}],
    )
    runners2 = {str(cases2[0]["id"]): _FakeRunner(uow, scope, {"output": "结果", "tool_traces": []})}
    service2 = _service(uow, runners2)
    asyncio.run(service2.run_batch(scope[0], run_id2))
    uow.commit()
    row = _results(uow, scope[0], run_id2)[0]
    assert row["status"] == "fail" and "send_email" in row["reason"]


def test_regex_and_json_schema_and_not_contains(uow, scope) -> None:
    # 每个评估器各起一批（F18.4：所选评估器跑全部 case，混在一起无法分别断言）
    _, run_a, cases_a = _seed(
        uow, scope, [{"input": {"message": "a"}}],
        [{"name": "正则", "type": "rule", "config": {"regex": r"多云\d+℃"}}],
    )
    _, run_b, cases_b = _seed(
        uow, scope, [{"input": {"message": "b"}}],
        [{"name": "不含", "type": "rule", "config": {"notContains": "抱歉"}}],
    )
    _, run_c, cases_c = _seed(
        uow, scope,
        [{"input": {"message": "c"}}, {"input": {"message": "d"}}],
        [{"name": "JSON", "type": "rule", "config": {"jsonSchema": True}}],
    )
    runners = {
        str(cases_a[0]["id"]): _FakeRunner(uow, scope, {"output": "今天多云18℃"}),
        str(cases_b[0]["id"]): _FakeRunner(uow, scope, {"output": "抱歉做不到"}),
        str(cases_c[0]["id"]): _FakeRunner(uow, scope, {"output": '{"k": 1}'}),
        str(cases_c[1]["id"]): _FakeRunner(uow, scope, {"output": "不是JSON"}),
    }
    service = _service(uow, runners)
    asyncio.run(service.run_batch(scope[0], run_a))
    asyncio.run(service.run_batch(scope[0], run_b))
    asyncio.run(service.run_batch(scope[0], run_c))
    uow.commit()
    assert _results(uow, scope[0], run_a)[0]["status"] == "pass"
    fail_b = _results(uow, scope[0], run_b)[0]
    assert fail_b["status"] == "fail" and "抱歉" in fail_b["reason"]
    statuses_c = sorted(r["status"] for r in _results(uow, scope[0], run_c))
    assert statuses_c == ["fail", "pass"]


class _FakeCeleryTask:
    def __init__(self, delay_error: Exception | None = None) -> None:
        self.delayed: list[Any] = []
        self._delay_error = delay_error

    def delay(self, *args: Any) -> None:
        if self._delay_error is not None:
            raise self._delay_error
        self.delayed.append(args)


def test_start_batch_creates_run_and_dispatches(uow, scope) -> None:
    repo, _, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}],
        [{"name": "包含", "type": "rule", "config": {"contains": "x"}}],
    )
    task = _FakeCeleryTask()
    ds = repo.list_datasets(scope[0])[0]
    run_id = _service_start(uow, scope, ds["id"], task, evaluator_ids=["e1"], graph_version=5)
    uow.commit()
    created = repo.get_eval_run(scope[0], run_id)
    assert created["status"] == "running"
    assert created["graph_version"] == 5
    assert task.delayed == [(str(scope[0]), str(run_id))]


def test_start_batch_broker_down_still_persists_run(uow, scope) -> None:
    repo, _, _ = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}],
        [{"name": "包含", "type": "rule", "config": {"contains": "x"}}],
    )
    task = _FakeCeleryTask(delay_error=OSError("broker down"))
    ds = repo.list_datasets(scope[0])[0]
    run_id = _service_start(uow, scope, ds["id"], task, evaluator_ids=["e1"], graph_version=1)
    uow.commit()
    # 投递失败降级：run 行保留（error 态可见），发起接口不炸（U12 保护）
    created = repo.get_eval_run(scope[0], run_id)
    assert created["status"] == "error"
    assert "broker" in (created["error_message"] or "")


def _service_start(uow, scope, dataset_id, task, *, evaluator_ids, graph_version):
    service = EvalRunService(
        eval_repo=EvalRepository(uow.session),
        run_repo=RunRepository(uow.session),
        runtime_factory=None,
        batch_task=task,
    )
    return service.start_batch(
        tenant_id=scope[0],
        application_id=scope[1],
        dataset_id=dataset_id,
        graph_version=graph_version,
        evaluator_ids=evaluator_ids,
        concurrency=2,
    )


class _StubRunRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def insert_run(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


def test_graph_runtime_passes_is_eval() -> None:
    # F18.3：评测 worker 直调须透传 is_eval，run 行落表归因（报告跳转依赖）
    from internal.domain.graph.runtime import GraphRuntime

    stub = _StubRunRepo()
    GraphRuntime({"nodes": []}, run_repo=stub, is_eval=True).ensure_run({"message": "x"})
    assert stub.rows[0]["is_eval"] is True


def test_graph_runtime_default_omits_is_eval_kwarg() -> None:
    # 默认不传：存量 insert_run 桩签名不带该键（对齐 parent_run_id 条件透传先例）
    from internal.domain.graph.runtime import GraphRuntime

    stub = _StubRunRepo()
    GraphRuntime({"nodes": []}, run_repo=stub).ensure_run({"message": "y"})
    assert "is_eval" not in stub.rows[0]


def test_run_batch_skips_finished_eval_run(uow, scope) -> None:
    """幂等守卫（批末 review#1）：批已终态后 broker 重投不得再执行任何 case。"""
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}],
        [{"name": "恒过", "type": "rule", "config": {}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果"}) for c in cases}
    asyncio.run(_service(uow, runners).run_batch(scope[0], run_id))
    uow.commit()
    assert len(_results(uow, scope[0], run_id)) == 2

    calls: list = []

    async def _sentinel(case, *_args):
        calls.append(case)
        raise AssertionError("重投不应再执行 case")

    service = EvalRunService(
        eval_repo=repo, run_repo=RunRepository(uow.session), runtime_factory=_sentinel
    )
    asyncio.run(service.run_batch(scope[0], run_id))
    assert calls == []
    assert len(_results(uow, scope[0], run_id)) == 2


def test_run_batch_replay_clears_previous_results(uow, scope) -> None:
    """中途被杀后重投（状态仍 running）：执行前清理本批旧结果行，重放不重复计数。"""
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}],
        [{"name": "恒过", "type": "rule", "config": {}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果"}) for c in cases}
    asyncio.run(_service(uow, runners).run_batch(scope[0], run_id))
    uow.commit()
    assert len(_results(uow, scope[0], run_id)) == 2

    # 模拟 worker 中途被杀：结果已部分/全部落库但批状态回到 running 被重投
    repo.update_eval_run(run_id, status="running")
    uow.commit()
    asyncio.run(_service(uow, runners).run_batch(scope[0], run_id))
    uow.commit()
    rows = _results(uow, scope[0], run_id)
    assert len(rows) == 2
    assert repo.get_eval_run(scope[0], run_id)["progress"]["done"] == 2


def test_evaluator_level_judge_model_resolution(uow, scope) -> None:
    """M4-d T-d7：评估器级 judgeModel 端到端解析（PRD 第 20 节挂账项收口）。

    config.model 指定的评估器用按模型解析出的客户端打分；同模型批内缓存只
    解析一次；缺省键走空串（消费方回退全局默认）。
    """
    _, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}],
        [
            {"name": "默认裁判", "type": "llm_judge", "config": {"passScore": 7}},
            {"name": "严格裁判", "type": "llm_judge", "config": {"passScore": 7, "model": "judge-g"}},
        ],
    )
    default_llm = _FakeJudgeLLM('{"score": 8, "passed": true, "critique": ""}')
    strict_llm = _FakeJudgeLLM('{"score": 3, "passed": false, "critique": "G 模型判定的事实错误"}')
    requested: list[str] = []

    def factory(model_id: str = "") -> _FakeJudgeLLM:
        requested.append(model_id)
        return strict_llm if model_id == "judge-g" else default_llm

    runners = {str(cases[0]["id"]): _FakeRunner(uow, scope, {"output": "回答"})}
    service = _service(uow, runners, judge_llm_factory=factory)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    assert "" in requested and "judge-g" in requested
    assert requested.count("judge-g") == 1
    row = _results(uow, scope[0], run_id)[0]
    assert row["status"] == "fail"
    assert row["score"] == 6  # (8+3)/2 均值四舍五入
    assert "G 模型判定的事实错误" in row["reason"]
    assert len(default_llm.calls) == 1 and len(strict_llm.calls) == 1


def test_judge_transport_error_marks_case_failed_not_batch(uow, scope) -> None:
    """M4-d 批末 review P2-4：judge 模型传输层异常不得炸整批——
    该 case 记 fail 行、reason 带异常摘要，批正常收尾（与门侧 fail-open 同容错口径）。"""
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}, {"input": {"message": "b"}}],
        [{"name": "裁判", "type": "llm_judge", "config": {"passScore": 7}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果ok"}) for c in cases}

    class _BrokenJudgeLLM:
        async def chat(self, **kwargs: Any):
            raise ConnectionError("judge 服务暂不可用")

    service = _service(uow, runners, judge_llm=_BrokenJudgeLLM())
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    done = repo.get_eval_run(scope[0], run_id)
    assert done["status"] == "completed"
    assert done["progress"] == {"total": 2, "done": 2, "passed": 0, "failed": 2, "errored": 0}
    rows = _results(uow, scope[0], run_id)
    assert all(r["status"] == "fail" for r in rows)
    assert all("judge 调用失败" in (r["reason"] or "") for r in rows)


def test_evaluator_pass_score_decided_by_consumer(uow, scope) -> None:
    """M4-d 批末 review：评估侧判定线与运行时质量门同源——按 config.passScore 自判，
    不信模型拼写的 passed 字段（严格评估器不漂移到内核默认 7）。"""
    repo, run_id, cases = _seed(
        uow,
        scope,
        [{"input": {"message": "a"}}],
        [{"name": "严格裁判", "type": "llm_judge", "config": {"passScore": 9}}],
    )
    runners = {str(c["id"]): _FakeRunner(uow, scope, {"output": "结果ok"}) for c in cases}
    judge_llm = _FakeJudgeLLM('{"score": 8, "passed": true, "critique": "轻微瑕疵"}')
    service = _service(uow, runners, judge_llm=judge_llm)
    asyncio.run(service.run_batch(scope[0], run_id))
    uow.commit()

    row = _results(uow, scope[0], run_id)[0]
    assert row["status"] == "fail"  # score 8 < passScore 9，模型自称 passed=true 不作数
    assert "轻微瑕疵" in row["reason"]
