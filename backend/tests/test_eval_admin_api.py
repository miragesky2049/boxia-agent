"""M4-d T-d4：评测管理端端点层回归（执行计划：验收 6 前半 + 越权 404）。

覆盖：dataset/case/evaluator CRUD 契约、跨租户越权 404、发起批（校验+投递+落行）、
报告详情与 diff、run 捕获为 case（F18.2 冷启动主通道）、未登录 401。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from web.admin.routers import eval_admin

BASE = "/api/v1/admin/eval"


class _FakeTask:
    def __init__(self) -> None:
        self.delayed: list[Any] = []

    def delay(self, *args: Any) -> None:
        self.delayed.append(args)


@pytest.fixture()
def fake_task(monkeypatch: pytest.MonkeyPatch) -> _FakeTask:
    task = _FakeTask()
    monkeypatch.setattr(eval_admin, "eval_batch_task", task)
    return task


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def app_id() -> UUID:
    """造一个平台应用（评测数据外键要求），返回 application_id。"""
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        aid = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO application (id, owner_type, name, description, is_enabled, "
                "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
                "VALUES (:id, 'platform', '评测端点应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
            ),
            {"id": aid},
        )
        # 评测发起要锁发布快照：预置一个图版本行
        uow.session.execute(
            text(
                "INSERT INTO application_graph_version (id, application_id, version, schema_json, changelog) "
                "VALUES (:id, :aid, 1, '{\"nodes\": []}'::jsonb, 'seed')"
            ),
            {"id": uuid4(), "aid": aid},
        )
        uow.commit()
        return aid
    finally:
        uow.close()


def _mk_dataset(client: TestClient, headers: dict, app_id: UUID, name: str = "集") -> str:
    resp = client.post(
        BASE + "/datasets",
        json={"application_id": str(app_id), "name": name, "description": "d"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_requires_login(client: TestClient) -> None:
    resp = client.get(BASE + "/datasets", params={"application_id": str(uuid4())})
    assert resp.status_code == 401


def test_dataset_crud_roundtrip(client: TestClient, headers: dict, app_id: UUID) -> None:
    ds_id = _mk_dataset(client, headers, app_id)
    listed = client.get(BASE + "/datasets", params={"application_id": str(app_id)}, headers=headers)
    assert [d["id"] for d in listed.json()["items"]] == [ds_id]
    got = client.get(f"{BASE}/datasets/{ds_id}", headers=headers)
    assert got.json()["application_id"] == str(app_id)
    patched = client.patch(
        f"{BASE}/datasets/{ds_id}", json={"name": "改名", "description": ""}, headers=headers
    )
    assert patched.json()["name"] == "改名"
    assert client.delete(f"{BASE}/datasets/{ds_id}", headers=headers).status_code == 204
    assert client.get(f"{BASE}/datasets/{ds_id}", headers=headers).status_code == 404


def test_case_crud_and_position(client: TestClient, headers: dict, app_id: UUID) -> None:
    ds_id = _mk_dataset(client, headers, app_id)
    first = client.post(
        f"{BASE}/datasets/{ds_id}/cases",
        json={"input": {"message": "问一"}, "expected": "答一"},
        headers=headers,
    )
    assert first.status_code == 201
    assert first.json()["position"] == 0
    second = client.post(
        f"{BASE}/datasets/{ds_id}/cases",
        json={
            "input": {"message": "问二", "images": ["http://x/y.png"]},
            "expected_tool_calls": {"must_call": ["lookup_city"]},
        },
        headers=headers,
    )
    assert second.json()["position"] == 1
    cid = second.json()["id"]
    patched = client.patch(
        f"{BASE}/cases/{cid}",
        json={"input": {"message": "改二"}, "expected": "新答"},
        headers=headers,
    )
    assert patched.json()["input"] == {"message": "改二"}
    cases = client.get(f"{BASE}/datasets/{ds_id}/cases", headers=headers).json()["items"]
    assert len(cases) == 2
    assert client.delete(f"{BASE}/cases/{cid}", headers=headers).status_code == 204


def test_evaluator_crud_and_bad_type(client: TestClient, headers: dict, app_id: UUID) -> None:
    rule = client.post(
        BASE + "/evaluators",
        json={"name": "包含", "type": "rule", "config": {"contains": "多云"}},
        headers=headers,
    )
    assert rule.status_code == 201
    judge = client.post(
        BASE + "/evaluators",
        json={"name": "裁判", "type": "llm_judge", "config": {"passScore": 7}},
        headers=headers,
    )
    listed = client.get(BASE + "/evaluators", params={"type": "llm_judge"}, headers=headers)
    assert [e["id"] for e in listed.json()["items"]] == [judge.json()["id"]]
    bad = client.post(
        BASE + "/evaluators", json={"name": "坏", "type": "magic", "config": {}}, headers=headers
    )
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    assert (
        client.delete(f"{BASE}/evaluators/{rule.json()['id']}", headers=headers).status_code == 204
    )


def test_cross_tenant_resource_returns_404(client: TestClient, headers: dict, app_id: UUID) -> None:
    """越权口径：他租户资源按不存在处理（repo 查询带 tenant 硬条件）。"""
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        other_tenant = uuid4()
        uow.session.execute(
            text("INSERT INTO tenants (id, code, name) VALUES (:id, :code, '越权测试租户')"),
            {"id": other_tenant, "code": f"e2e-eval-{other_tenant}"},
        )
        ds = EvalRepository(uow.session).create_dataset(
            tenant_id=other_tenant, application_id=app_id, name="他租户集"
        )
        uow.commit()
        ds_id = str(ds["id"])
    finally:
        uow.close()
    assert client.get(f"{BASE}/datasets/{ds_id}", headers=headers).status_code == 404
    assert client.delete(f"{BASE}/datasets/{ds_id}", headers=headers).status_code == 404


def test_start_eval_run_validates_and_dispatches(
    client: TestClient, headers: dict, app_id: UUID, fake_task: _FakeTask
) -> None:
    ds_id = _mk_dataset(client, headers, app_id)
    ev = client.post(
        BASE + "/evaluators",
        json={"name": "恒过", "type": "rule", "config": {}},
        headers=headers,
    )
    ev_id = ev.json()["id"]
    resp = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "application_id": str(app_id),
            "graph_version": 1,
            "evaluator_ids": [ev_id],
            "concurrency": 6,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["eval_run_id"]
    # clamp 6→4 记入初始 progress；投递二元组 (tenant, eval_run)
    assert fake_task.delayed == [(str(PLATFORM_TENANT_ID), run_id)]
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        row = EvalRepository(uow.session).get_eval_run(PLATFORM_TENANT_ID, UUID(run_id))
        assert row is not None and row["status"] == "running"
        assert row["progress"] == {"concurrency": 4}
        assert row["graph_version"] == 1 and row["dataset_id"] == UUID(ds_id)
    finally:
        uow.close()

    bad = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "application_id": str(app_id),
            "graph_version": 99,
            "evaluator_ids": [ev_id],
        },
        headers=headers,
    )
    assert bad.status_code == 422
    bad_ev = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "application_id": str(app_id),
            "graph_version": 1,
            "evaluator_ids": [str(uuid4())],
        },
        headers=headers,
    )
    assert bad_ev.status_code == 422


def test_eval_run_detail_and_diff(
    client: TestClient, headers: dict, app_id: UUID, fake_task: _FakeTask
) -> None:
    ds_id = _mk_dataset(client, headers, app_id)
    for msg in ("a", "b"):
        client.post(
            f"{BASE}/datasets/{ds_id}/cases", json={"input": {"message": msg}}, headers=headers
        )
    ev = client.post(
        BASE + "/evaluators", json={"name": "恒过", "type": "rule", "config": {}}, headers=headers
    )
    started = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "application_id": str(app_id),
            "graph_version": 1,
            "evaluator_ids": [ev.json()["id"]],
        },
        headers=headers,
    )
    run_id = started.json()["eval_run_id"]
    # 端点不发 worker：手工把批推到完成态再验报告契约
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        repo = EvalRepository(uow.session)
        cases = repo.list_cases(PLATFORM_TENANT_ID, UUID(ds_id))
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": PLATFORM_TENANT_ID,
                    "eval_run_id": UUID(run_id),
                    "case_id": cases[0]["id"],
                    "status": "pass",
                    "score": 9,
                    "reason": "",
                    "judge_usage": None,
                    "source": "eval_run",
                },
                {
                    "id": uuid4(),
                    "tenant_id": PLATFORM_TENANT_ID,
                    "eval_run_id": UUID(run_id),
                    "case_id": cases[1]["id"],
                    "status": "fail",
                    "score": 4,
                    "reason": "事实错误",
                    "judge_usage": None,
                    "source": "eval_run",
                },
            ]
        )
        repo.update_eval_run(UUID(run_id), status="completed", progress={"total": 2, "done": 2})
        uow.commit()
    finally:
        uow.close()
    detail = client.get(f"{BASE}/eval-runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["run"]["status"] == "completed"
    assert len(body["results"]) == 2
    assert body["summary"]["pass_rate"] == 0.5
    assert body["summary"]["errored"] == 0

    started2 = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "application_id": str(app_id),
            "graph_version": 1,
            "evaluator_ids": [ev.json()["id"]],
        },
        headers=headers,
    )
    run_b = started2.json()["eval_run_id"]
    diff = client.get(
        BASE + "/eval-runs/diff", params={"run_a": run_id, "run_b": run_b}, headers=headers
    )
    assert diff.status_code == 200
    items = diff.json()["items"]
    assert len(items) == 2
    row_a = next(row for row in items if row["status_a"] == "pass")
    assert row_a["status_b"] is None


def test_capture_case_from_run(client: TestClient, headers: dict, app_id: UUID) -> None:
    run_uuid = uuid4()
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        # 对齐生产形态：run.input 落 invoke 入参（问句键为 input，非 message）
        RunRepository(uow.session).insert_run(
            run_id=run_uuid,
            tenant_id=PLATFORM_TENANT_ID,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"input": "北京天气？"},
            thread_id=f"cap-{run_uuid}",
        )
        uow.session.execute(
            text(
                "UPDATE run SET output = CAST(:o AS JSONB), execute_status='success' WHERE id=:id"
            ),
            {"o": '{"output": "晴 25℃"}', "id": run_uuid},
        )
        uow.commit()
    finally:
        uow.close()
    ds_id = _mk_dataset(client, headers, app_id)
    resp = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run",
        json={"run_id": str(run_uuid)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    case = resp.json()
    assert case["input"] == {"message": "北京天气？"}
    assert case["expected"] == "晴 25℃"
    missing = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run",
        json={"run_id": str(uuid4())},
        headers=headers,
    )
    assert missing.status_code == 404


def test_quality_summary_skeleton(
    client: TestClient, headers: dict, app_id: UUID, fake_task: _FakeTask
) -> None:
    """T-d5 骨架：7 日窗口内评测批通过率 + judge 采样均分/低分数（空态全零）。"""
    empty = client.get(f"/api/v1/admin/apps/{app_id}/quality/summary", headers=headers)
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["window_days"] == 7
    assert body["eval_batches"] == {"count": 0, "latest_pass_rate": None}
    assert body["runtime_samples"] == {"count": 0, "avg_score": None, "low_score_count": 0}

    ds_id = _mk_dataset(client, headers, app_id)
    for msg in ("a", "b"):
        client.post(
            f"{BASE}/datasets/{ds_id}/cases", json={"input": {"message": msg}}, headers=headers
        )
    ev = client.post(
        BASE + "/evaluators", json={"name": "恒过", "type": "rule", "config": {}}, headers=headers
    )
    started = client.post(
        BASE + "/eval-runs",
        json={
            "dataset_id": ds_id,
            "graph_version": 1,
            "evaluator_ids": [ev.json()["id"]],
        },
        headers=headers,
    )
    run_uuid = uuid4()
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        repo = EvalRepository(uow.session)
        cases = repo.list_cases(PLATFORM_TENANT_ID, UUID(ds_id))
        eval_run_id = UUID(started.json()["eval_run_id"])
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": PLATFORM_TENANT_ID,
                    "eval_run_id": eval_run_id,
                    "case_id": cases[i]["id"],
                    "status": st,
                    "score": sc,
                    "reason": "",
                    "judge_usage": None,
                    "source": "eval_run",
                }
                for i, (st, sc) in enumerate((("pass", 9), ("fail", 4)))
            ]
        )
        repo.update_eval_run(eval_run_id, status="completed")
        # judge 采样行：source=runtime_sample 需挂真实 run 行（看板按 run 归因到应用）
        RunRepository(uow.session).insert_run(
            run_id=run_uuid,
            tenant_id=PLATFORM_TENANT_ID,
            workflow_id=app_id,
            graph_snapshot={},
            input_data={"message": "线上问句"},
            thread_id=f"q-{run_uuid}",
        )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": PLATFORM_TENANT_ID,
                    "eval_run_id": None,
                    "run_id": run_uuid,
                    "case_id": None,
                    "status": "fail",
                    "score": 3,
                    "reason": "漏答关键信息",
                    "judge_usage": None,
                    "source": "runtime_sample",
                }
            ]
        )
        uow.commit()
    finally:
        uow.close()
    got = client.get(f"/api/v1/admin/apps/{app_id}/quality/summary", headers=headers).json()
    assert got["eval_batches"] == {"count": 1, "latest_pass_rate": 0.5}
    assert got["runtime_samples"] == {"count": 1, "avg_score": 3.0, "low_score_count": 1}


def test_quality_summary_board_trend_and_flywheel(
    client: TestClient, headers: dict, app_id: UUID, fake_task: _FakeTask
) -> None:
    """T-d9 看板与飞轮：7 日日均趋势 + 低分清单（带问句）→ 一键转评测集（from-run 消费）。

    采样行按对话租户（非平台）落库——同时锁定 T-d9 跨租户可见性修复。
    """
    run_low, run_high, run_edge = uuid4(), uuid4(), uuid4()
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        code = f"bd-{uuid4().hex[:8]}"
        tenant = uow.tenants.create({"code": code, "name": f"看板租户{code}"})
        runs = RunRepository(uow.session)
        repo = EvalRepository(uow.session)
        for rid in (run_low, run_high, run_edge):
            runs.insert_run(
                run_id=rid,
                tenant_id=tenant.id,
                workflow_id=app_id,
                graph_snapshot={},
                input_data={"input": f"线上问句{rid}"},
                thread_id=f"b-{rid}",
            )
            # 采样只发生在 success 终局后：播种对齐生产形态（from-run 捕获校验依赖此态）
            uow.session.execute(
                text(
                    "UPDATE run SET execute_status='success', output = CAST(:o AS JSONB) "
                    "WHERE id=:id"
                ),
                {"o": '{"output": "线上回答"}', "id": rid},
            )
        repo.insert_results(
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant.id,
                    "eval_run_id": None,
                    "run_id": run_low,
                    "case_id": None,
                    "status": "fail",
                    "score": 3,
                    "reason": "漏答关键信息",
                    "judge_usage": None,
                    "source": "runtime_sample",
                },
                {
                    "id": uuid4(),
                    "tenant_id": tenant.id,
                    "eval_run_id": None,
                    "run_id": run_high,
                    "case_id": None,
                    "status": "pass",
                    "score": 9,
                    "reason": "回答完整",
                    "judge_usage": None,
                    "source": "runtime_sample",
                },
                # 批末 review F1：滚动窗口会把最旧桶日前一天尾段的低分样本混进概览/清单，
                # 但日桶无该日 → 与 trend 口径错位；日历日窗口应整行排除
                {
                    "id": uuid4(),
                    "tenant_id": tenant.id,
                    "eval_run_id": None,
                    "run_id": run_edge,
                    "case_id": None,
                    "status": "fail",
                    "score": 1,
                    "reason": "窗口外旧样本",
                    "judge_usage": None,
                    "source": "runtime_sample",
                },
            ]
        )
        oldest_day = datetime.now(UTC).date() - timedelta(days=6)
        edge_ts = datetime(
            oldest_day.year, oldest_day.month, oldest_day.day, tzinfo=UTC
        ) - timedelta(minutes=1)
        uow.session.execute(
            text(
                "UPDATE eval_result SET created_at = :ts WHERE run_id = :rid "
                "AND source = 'runtime_sample'"
            ),
            {"ts": edge_ts, "rid": run_edge},
        )
        uow.commit()
    finally:
        uow.close()

    body = client.get(f"/api/v1/admin/apps/{app_id}/quality/summary?days=7", headers=headers).json()
    assert body["runtime_samples"] == {"count": 2, "avg_score": 6.0, "low_score_count": 1}
    trend = body["trend"]
    assert len(trend) == 7
    today = datetime.now(UTC).date()
    # 窗口末日必须覆盖今天（跨 UTC 零点落桶不敏感：起点随 days 递推）
    assert trend[-1]["date"] == today.isoformat()
    assert [point["date"] for point in trend] == [
        (today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)
    ]
    assert sum(point["count"] for point in trend) == 2
    # F1 不变式：概览计数与逐日桶总和必须同源同口径（同一份窗口内样本）
    assert body["runtime_samples"]["count"] == sum(point["count"] for point in trend)
    day_buckets = [point for point in trend if point["count"] == 2]
    assert len(day_buckets) == 1 and day_buckets[0]["avg_score"] == 6.0

    low_items = body["low_score_items"]
    assert len(low_items) == 1
    item = low_items[0]
    assert item["run_id"] == str(run_low) and item["score"] == 3
    assert item["question"] == f"线上问句{run_low}"
    assert item["reason"] == "漏答关键信息"

    # 飞轮闭环：低分清单给出的 run_id 直接 from-run 转评测集，评测批可消费
    ds_id = _mk_dataset(client, headers, app_id)
    captured = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run",
        json={"run_id": item["run_id"]},
        headers=headers,
    )
    assert captured.status_code == 201, captured.text
    case = captured.json()
    assert case["input"] == {"message": f"线上问句{run_low}"}
    assert case["expected"] == "线上回答"


def test_dataset_create_requires_existing_application(client: TestClient, headers: dict) -> None:
    """悬空 application_id 应 422 而不是 FK 撞出误导性 409（批末 review#4）。"""
    resp = client.post(
        BASE + "/datasets",
        json={"application_id": str(uuid4()), "name": "悬空集", "description": ""},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_diff_requires_same_dataset(
    client: TestClient, headers: dict, app_id: UUID, fake_task: _FakeTask
) -> None:
    """跨数据集 diff 恒得 status_b=None 会静默失真，须 422（批末 review#5）。"""
    ev = client.post(
        BASE + "/evaluators", json={"name": "恒过", "type": "rule", "config": {}}, headers=headers
    )
    run_ids = []
    for name in ("集甲", "集乙"):
        ds_id = _mk_dataset(client, headers, app_id, name)
        client.post(
            f"{BASE}/datasets/{ds_id}/cases", json={"input": {"message": "x"}}, headers=headers
        )
        started = client.post(
            BASE + "/eval-runs",
            json={"dataset_id": ds_id, "graph_version": 1, "evaluator_ids": [ev.json()["id"]]},
            headers=headers,
        )
        assert started.status_code == 201, started.text
        run_ids.append(started.json()["eval_run_id"])
    resp = client.get(
        BASE + "/eval-runs/diff", params={"run_a": run_ids[0], "run_b": run_ids[1]}, headers=headers
    )
    assert resp.status_code == 422, resp.text


def test_capture_case_validates_source_run(client: TestClient, headers: dict, app_id: UUID) -> None:
    """捕获口径：非本应用 run→404；未正常结束→422；空问句→422（批末 review#2/#7）。"""
    ds_id = _mk_dataset(client, headers, app_id)
    other_app = uuid4()
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    run_foreign = uuid4()
    run_unfinished = uuid4()
    run_empty = uuid4()
    try:
        uow.session.execute(
            text(
                "INSERT INTO application (id, owner_type, name, description, is_enabled, "
                "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
                "VALUES (:id, 'platform', '捕获对照应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
            ),
            {"id": other_app},
        )
        for rid, wf in ((run_foreign, other_app), (run_unfinished, app_id), (run_empty, app_id)):
            RunRepository(uow.session).insert_run(
                run_id=rid,
                tenant_id=PLATFORM_TENANT_ID,
                workflow_id=wf,
                graph_snapshot={},
                input_data={"input": "问句"},
                thread_id=f"cap-{rid}",
            )
        uow.session.execute(
            text("UPDATE run SET execute_status='success' WHERE id IN (:a, :c)"),
            {"a": run_foreign, "c": run_empty},
        )
        uow.session.execute(
            text('UPDATE run SET input = \'{"input": ""}\'::jsonb WHERE id = :c'),
            {"c": run_empty},
        )
        uow.commit()
    finally:
        uow.close()
    foreign = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run",
        json={"run_id": str(run_foreign)},
        headers=headers,
    )
    assert foreign.status_code == 404, foreign.text
    unfinished = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run",
        json={"run_id": str(run_unfinished)},
        headers=headers,
    )
    assert unfinished.status_code == 422, unfinished.text
    empty = client.post(
        f"{BASE}/datasets/{ds_id}/cases/from-run", json={"run_id": str(run_empty)}, headers=headers
    )
    assert empty.status_code == 422, empty.text
