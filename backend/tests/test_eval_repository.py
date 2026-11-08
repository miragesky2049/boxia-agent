"""M4-d T-d2：评测五表仓储单测（真实 PG）+ run.is_eval 过滤。

覆盖：dataset/case/evaluator CRUD、case position 自动递增、eval_run 生命周期回写、
result 批量写与 diff 对齐、FK CASCADE、租户隔离、评测 run 默认从运行日志隐身。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository


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
    """造租户 + 应用（评测表外键要求），返回 (tenant_id, app_id)。"""
    code = f"ev-{uuid4().hex[:8]}"
    tenant = uow.tenants.create({"code": code, "name": f"评测租户{code}"})
    app_id = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '评测应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": app_id},
    )
    uow.commit()
    return tenant.id, app_id


def _repo(uow) -> EvalRepository:
    return EvalRepository(uow.session)


class TestDataset:
    def test_crud_roundtrip(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        created = repo.create_dataset(
            tenant_id=tenant_id, application_id=app_id, name="天气集", description="F18.2"
        )
        uow.commit()
        assert created["name"] == "天气集"
        fetched = repo.get_dataset(tenant_id, created["id"])
        assert fetched is not None and fetched["application_id"] == app_id
        assert repo.update_dataset(tenant_id, created["id"], name="改名集", description="")
        uow.commit()
        assert repo.get_dataset(tenant_id, created["id"])["name"] == "改名集"
        listed = repo.list_datasets(tenant_id, application_id=app_id)
        assert [d["id"] for d in listed] == [created["id"]]
        assert repo.delete_dataset(tenant_id, created["id"]) is True
        uow.commit()
        assert repo.get_dataset(tenant_id, created["id"]) is None

    def test_tenant_isolation(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        created = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="隔离集")
        uow.commit()
        assert repo.get_dataset(uuid4(), created["id"]) is None
        assert repo.list_datasets(uuid4()) == []


class TestCase:
    def test_position_auto_and_ordering(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        c1 = repo.add_case(tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "a"})
        c2 = repo.add_case(
            tenant_id=tenant_id,
            dataset_id=ds["id"],
            input_data={"message": "b"},
            expected="答案b",
            expected_tool_calls={"must_call": ["lookup_city"]},
        )
        uow.commit()
        assert (c1["position"], c2["position"]) == (0, 1)
        cases = repo.list_cases(tenant_id, ds["id"])
        assert [c["input"]["message"] for c in cases] == ["a", "b"]
        assert cases[1]["expected"] == "答案b"
        assert cases[1]["expected_tool_calls"] == {"must_call": ["lookup_city"]}

    def test_update_and_delete(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        case = repo.add_case(tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "a"})
        uow.commit()
        assert repo.update_case(
            tenant_id, case["id"], input_data={"message": "改"}, expected="新答案"
        )
        uow.commit()
        updated = repo.list_cases(tenant_id, ds["id"])[0]
        assert updated["input"] == {"message": "改"} and updated["expected"] == "新答案"
        assert repo.delete_case(tenant_id, case["id"]) is True
        uow.commit()
        assert repo.list_cases(tenant_id, ds["id"]) == []

    def test_dataset_cascade_removes_cases(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        repo.add_case(tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "a"})
        uow.commit()
        repo.delete_dataset(tenant_id, ds["id"])
        uow.commit()
        assert repo.list_cases(tenant_id, ds["id"]) == []


class TestEvaluator:
    def test_crud_and_type_filter(self, uow, scope) -> None:
        tenant_id, _ = scope
        repo = _repo(uow)
        rule = repo.create_evaluator(
            tenant_id=tenant_id, name="包含", type_="rule", config={"contains": "多云"}
        )
        judge = repo.create_evaluator(
            tenant_id=tenant_id, name="裁判", type_="llm_judge", config={"passScore": 7}
        )
        uow.commit()
        assert len(repo.list_evaluators(tenant_id)) == 2
        assert [e["id"] for e in repo.list_evaluators(tenant_id, type_="llm_judge")] == [
            judge["id"]
        ]
        assert repo.update_evaluator(
            tenant_id, rule["id"], name="包含2", type_="rule", config={"contains": "晴"}
        )
        uow.commit()
        assert repo.get_evaluator(tenant_id, rule["id"])["config"] == {"contains": "晴"}
        assert repo.delete_evaluator(tenant_id, judge["id"]) is True
        uow.commit()
        assert repo.get_evaluator(tenant_id, judge["id"]) is None

    def test_type_check_constraint(self, uow, scope) -> None:
        tenant_id, _ = scope
        repo = _repo(uow)
        with pytest.raises(IntegrityError):
            repo.create_evaluator(tenant_id=tenant_id, name="坏", type_="magic", config={})


class TestEvalRunAndResults:
    def test_run_lifecycle(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        run_id = uuid4()
        run_ev_ids = [str(uuid4())]
        repo.insert_eval_run(
            run_id=run_id,
            tenant_id=tenant_id,
            application_id=app_id,
            graph_version=3,
            dataset_id=ds["id"],
            evaluator_ids=run_ev_ids,
        )
        uow.commit()
        run = repo.get_eval_run(tenant_id, run_id)
        assert run is not None and run["status"] == "running"
        assert run["progress"] == {} and run["graph_version"] == 3
        repo.update_eval_run(
            run_id,
            status="completed",
            progress={"total": 2, "done": 2},
            usage={"total_tokens": 120},
        )
        uow.commit()
        done = repo.get_eval_run(tenant_id, run_id)
        assert done["status"] == "completed"
        assert done["progress"]["done"] == 2
        assert done["usage"]["total_tokens"] == 120
        listed = repo.list_eval_runs(tenant_id, app_id)
        assert [r["id"] for r in listed] == [run_id]
        # 列表序列化（eval_admin._run_out）按硬键取 evaluator_ids，SELECT 缺列会 500，必须随列表返回
        assert listed[0]["evaluator_ids"] == run_ev_ids

    def test_results_batch_list_and_diff(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        case_a = repo.add_case(
            tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "a"}
        )
        case_b = repo.add_case(
            tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "b"}
        )
        run_a, run_b = uuid4(), uuid4()
        for rid in (run_a, run_b):
            repo.insert_eval_run(
                run_id=rid,
                tenant_id=tenant_id,
                application_id=app_id,
                graph_version=1,
                dataset_id=ds["id"],
                evaluator_ids=[],
            )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": run_a,
                    "case_id": case_a["id"],
                    "status": "pass",
                    "score": 9,
                    "reason": "",
                    "judge_usage": None,
                    "source": "eval_run",
                },
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": run_a,
                    "case_id": case_b["id"],
                    "status": "fail",
                    "score": 4,
                    "reason": "事实错误",
                    "judge_usage": None,
                    "source": "eval_run",
                },
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": run_b,
                    "case_id": case_a["id"],
                    "status": "fail",
                    "score": 3,
                    "reason": "回归",
                    "judge_usage": None,
                    "source": "eval_run",
                },
                # run_b 未跑 case_b：diff 行应出现且 b 侧为 NULL
            ]
        )
        uow.commit()
        results = repo.list_results(tenant_id, run_a)
        assert len(results) == 2
        assert results[0]["case_id"] == case_a["id"] and results[1]["reason"] == "事实错误"
        diff = repo.diff_results(tenant_id, run_a, run_b)
        by_case = {row["case_id"]: row for row in diff}
        assert by_case[case_a["id"]]["status_a"] == "pass"
        assert by_case[case_a["id"]]["status_b"] == "fail"
        assert by_case[case_b["id"]]["status_a"] == "fail"
        assert by_case[case_b["id"]]["status_b"] is None

    def test_runtime_sample_result_without_eval_run(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        # 采样结果关联真实会话 run（看板按应用归因需 JOIN run 归因）
        sample_run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=sample_run_id,
            tenant_id=tenant_id,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"input": "线上问句甲"},
            thread_id=f"t-{sample_run_id}",
        )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": None,
                    "run_id": sample_run_id,
                    "case_id": None,
                    "status": "pass",
                    "score": 8,
                    "reason": "",
                    "judge_usage": {"total_tokens": 30},
                    "source": "runtime_sample",
                }
            ]
        )
        # T-d9 看板可见性修复：worker 按 run 的对话租户落采样行（非平台租户），
        # 看板只按应用归因；若沿用平台租户过滤，线上采样将恒不可见
        other_run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=other_run_id,
            tenant_id=PLATFORM_TENANT_ID,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"message": "线上问句乙"},
            thread_id=f"t-{other_run_id}",
        )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": PLATFORM_TENANT_ID,
                    "eval_run_id": None,
                    "run_id": other_run_id,
                    "case_id": None,
                    "status": "fail",
                    "score": 3,
                    "reason": "漏答",
                    "judge_usage": None,
                    "source": "runtime_sample",
                }
            ]
        )
        uow.commit()
        rows = repo.list_runtime_samples(app_id, days=7)
        by_run = {row["run_id"]: row for row in rows}
        assert set(by_run) == {sample_run_id, other_run_id}
        assert by_run[sample_run_id]["judge_usage"]["total_tokens"] == 30
        assert by_run[sample_run_id]["run_input"] == {"input": "线上问句甲"}
        assert repo.list_runtime_samples(uuid4(), days=7) == []

    def test_runtime_samples_window_aligned_to_utc_calendar_days(self, uow, scope) -> None:
        """批末 review F1：窗口必须与看板 trend 日桶同口径——UTC 日历日，起点=最旧桶日 00:00。
        滚动窗口（now - N 天）会把最旧桶日前一天（today-7）尾段样本混进概览指标，
        但日桶表无该日 → sum(trend.count) < runtime_samples.count，边界样本静默错位。"""
        tenant_id, app_id = scope
        repo = _repo(uow)
        oldest_day = datetime.now(UTC).date() - timedelta(days=6)
        oldest_bucket_start = datetime(
            oldest_day.year, oldest_day.month, oldest_day.day, tzinfo=UTC
        )
        seeds = [
            # 最旧桶日前一天 23:59（UTC）：日历日窗口必须排除（滚动窗口会误收）
            oldest_bucket_start - timedelta(minutes=1),
            # 最旧桶日 00:00:30（UTC）：窗口内最老样本，必须保留（防止窗口被多切一天）
            oldest_bucket_start + timedelta(seconds=30),
            # 窗口外（8 天前）：恒排除
            datetime.now(UTC) - timedelta(days=8),
        ]
        scores = [3, 8, 2]
        run_ids = [uuid4() for _ in seeds]
        row_ids = [uuid4() for _ in seeds]
        for tag, rid in zip(("edge", "boundary", "stale"), run_ids, strict=True):
            RunRepository(uow.session).insert_run(
                run_id=rid,
                tenant_id=tenant_id,
                workflow_id=app_id,
                graph_snapshot={},
                input_data={"input": f"线上问句{tag}"},
                thread_id=f"t-{rid}",
            )
        repo.insert_results(
            [
                {
                    "id": row_id,
                    "tenant_id": tenant_id,
                    "eval_run_id": None,
                    "run_id": rid,
                    "case_id": None,
                    "status": "pass" if score >= 5 else "fail",
                    "score": score,
                    "reason": "",
                    "judge_usage": None,
                    "source": "runtime_sample",
                }
                for row_id, rid, score in zip(row_ids, run_ids, scores, strict=True)
            ]
        )
        # created_at 走库默认值无法由 insert_results 指定，播种后按行回拨到窗口边界
        for row_id, created_at in zip(row_ids, seeds, strict=True):
            uow.session.execute(
                text("UPDATE eval_result SET created_at = :ts WHERE id = :id"),
                {"ts": created_at, "id": row_id},
            )
        uow.commit()
        got = {row["run_id"] for row in repo.list_runtime_samples(app_id, days=7)}
        assert got == {run_ids[1]}

    def test_runtime_sample_unique_index_blocks_concurrent_double_insert(self, uow, scope) -> None:
        """批末 review P2-1：双 worker 并行探测竞态由 DB 唯一索引兜底——
        同 run 第二条 runtime_sample 行必须撞约束（事务回滚 = 不重复计费）。"""
        tenant_id, app_id = scope
        repo = _repo(uow)
        sample_run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=sample_run_id,
            tenant_id=tenant_id,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"message": "hi"},
            thread_id=f"t-{sample_run_id}",
        )
        row = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "eval_run_id": None,
            "run_id": sample_run_id,
            "case_id": None,
            "status": "pass",
            "score": 8,
            "reason": "",
            "judge_usage": None,
            "source": "runtime_sample",
        }
        repo.insert_results([row])
        uow.commit()
        dup = {**row, "id": uuid4(), "score": 9}
        with pytest.raises(IntegrityError):
            repo.insert_results([dup])

    def test_has_runtime_sample_probe(self, uow, scope) -> None:
        """T-d8 幂等探测：任务重投不重复计费；eval_run 结果行与 runtime_gate 不算采样。"""
        tenant_id, app_id = scope
        repo = _repo(uow)
        sample_run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=sample_run_id,
            tenant_id=tenant_id,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"message": "hi"},
            thread_id=f"t-{sample_run_id}",
        )
        assert repo.has_runtime_sample(sample_run_id) is False
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": None,
                    "run_id": sample_run_id,
                    "case_id": None,
                    "status": "pass",
                    "score": 8,
                    "reason": "",
                    "judge_usage": None,
                    "source": "runtime_sample",
                }
            ]
        )
        uow.commit()
        assert repo.has_runtime_sample(sample_run_id) is True
        assert repo.has_runtime_sample(uuid4()) is False

    def test_eval_run_cascade_removes_results(self, uow, scope) -> None:
        tenant_id, app_id = scope
        repo = _repo(uow)
        ds = repo.create_dataset(tenant_id=tenant_id, application_id=app_id, name="集")
        case = repo.add_case(tenant_id=tenant_id, dataset_id=ds["id"], input_data={"message": "a"})
        run_id = uuid4()
        repo.insert_eval_run(
            run_id=run_id,
            tenant_id=tenant_id,
            application_id=app_id,
            graph_version=1,
            dataset_id=ds["id"],
            evaluator_ids=[],
        )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "eval_run_id": run_id,
                    "case_id": case["id"],
                    "status": "pass",
                    "score": 9,
                    "reason": "",
                    "judge_usage": None,
                    "source": "eval_run",
                }
            ]
        )
        uow.commit()
        uow.session.execute(text("DELETE FROM eval_run WHERE id = :id"), {"id": run_id})
        uow.commit()
        assert repo.list_results(tenant_id, run_id) == []


class TestRunIsEval:
    """0080 + F18.3：评测 run 落表归因，运行日志默认隐身但详情可查（报告跳转）。"""

    def _insert(self, uow, scope, *, is_eval: bool) -> Any:
        tenant_id, app_id = scope
        run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=run_id,
            tenant_id=tenant_id,
            workflow_id=app_id,
            graph_snapshot={"nodes": []},
            input_data={"message": "评测输入"},
            thread_id=f"t-{run_id}",
            is_eval=is_eval,
        )
        uow.commit()
        return tenant_id, app_id, run_id

    def test_eval_runs_hidden_from_default_list(self, uow, scope) -> None:
        normal = self._insert(uow, scope, is_eval=False)
        eval_run = self._insert(uow, scope, is_eval=True)
        tenant_id, app_id = normal[0], normal[1]
        listed = RunRepository(uow.session).list_runs(tenant_id, workflow_id=app_id)
        ids = {row["id"] for row in listed}
        assert normal[2] in ids and eval_run[2] not in ids

    def test_get_run_exposes_is_eval_flag(self, uow, scope) -> None:
        tenant_id, _, run_id = self._insert(uow, scope, is_eval=True)
        row = RunRepository(uow.session).get_run(run_id)
        assert row is not None and row["is_eval"] is True

    def test_insert_defaults_to_normal_run(self, uow, scope) -> None:
        tenant_id, app_id = scope
        run_id = uuid4()
        RunRepository(uow.session).insert_run(
            run_id=run_id,
            tenant_id=tenant_id,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={},
            thread_id="t-default",
        )
        uow.commit()
        assert RunRepository(uow.session).get_run(run_id)["is_eval"] is False
