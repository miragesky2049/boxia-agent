"""管理端评测接口（M4-d F18.2/F18.4/F18.5）：五表 CRUD + 批发起 + 报告/diff + run 捕获。

评测数据统一归属 PLATFORM_TENANT_ID：admin 是产品运营视角，数据集/评估器库供全部
平台应用使用；租户自助评测属未来按来源换 tenant 的扩展，不改表结构。越权一律 404
（仓储查询带 tenant 硬条件，他租户行查不到即不存在）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from internal.application.apps.eval_run_service import EvalRunService, extract_answer_text
from internal.application.errors import NotFoundError, ValidationError
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from web.admin.schemas.eval import (
    CaptureCasePayload,
    CasePayload,
    DatasetPayload,
    DatasetUpdatePayload,
    EvaluatorPayload,
    EvaluatorUpdatePayload,
    StartEvalRunPayload,
)
from web.deps.auth import require_platform_admin
from web.deps.db import UowDep
from web.tasks.eval_tasks import run_batch as eval_batch_task

router = APIRouter(
    prefix="/eval",
    tags=["eval-admin"],
    dependencies=[Depends(require_platform_admin)],
)


def get_eval_repo(uow: UowDep) -> EvalRepository:
    return EvalRepository(uow.session)


EvalRepoDep = Annotated[EvalRepository, Depends(get_eval_repo)]

# judge 打分统一 0~10 尺度，低分线取一半（F18.6 看板低分清单口径）
_LOW_SCORE_THRESHOLD = 5
# 低分清单一次透出上限：飞轮入口逐条人工判读，超窗口的历史行由 days 收窄即可
_LOW_SCORE_LIST_LIMIT = 20


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _dataset_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "application_id": str(row["application_id"]),
        "name": row["name"],
        "description": row["description"],
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _case_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "dataset_id": str(row["dataset_id"]),
        "input": row["input"],
        "expected": row["expected"],
        "expected_tool_calls": row.get("expected_tool_calls"),
        "position": row["position"],
    }


def _evaluator_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "type": row["type"],
        "config": row["config"],
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _run_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        # list_eval_runs 不返回 application_id（详情路由才有），列表序列化容错
        "application_id": str(row["application_id"]) if row.get("application_id") else None,
        "graph_version": row["graph_version"],
        "dataset_id": str(row["dataset_id"]),
        "evaluator_ids": row["evaluator_ids"],
        "status": row["status"],
        "progress": row["progress"],
        "usage": row["usage"],
        "error_message": row.get("error_message"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _result_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "case_id": str(row["case_id"]) if row.get("case_id") else None,
        "status": row["status"],
        "score": row["score"],
        "reason": row["reason"],
        "judge_usage": row.get("judge_usage"),
        "source": row["source"],
        "created_at": _iso(row.get("created_at")),
    }


def _require_dataset(repo: EvalRepository, dataset_id: UUID) -> dict[str, Any]:
    ds = repo.get_dataset(PLATFORM_TENANT_ID, dataset_id)
    if ds is None:
        raise NotFoundError("评测数据集不存在")
    return ds


def _require_eval_run(repo: EvalRepository, run_id: UUID) -> dict[str, Any]:
    run = repo.get_eval_run(PLATFORM_TENANT_ID, run_id)
    if run is None:
        raise NotFoundError("评测批任务不存在")
    return run


# ========== eval_dataset ==========
@router.get("/datasets")
def list_datasets(
    repo: EvalRepoDep,
    application_id: UUID | None = Query(None, description="按应用过滤；缺省=平台全部数据集"),
) -> dict:
    """数据集列表（时近倒序）。"""
    items = repo.list_datasets(PLATFORM_TENANT_ID, application_id=application_id)
    return {"items": [_dataset_out(row) for row in items]}


@router.post("/datasets", status_code=status.HTTP_201_CREATED)
def create_dataset(payload: DatasetPayload, repo: EvalRepoDep, uow: UowDep) -> dict:
    """创建评测数据集（归属平台租户；应用不存在给 422 而非 FK 撞 409）。"""
    if ApplicationRepository(uow.session).get_application(payload.application_id) is None:
        raise ValidationError("应用不存在")
    created = repo.create_dataset(
        tenant_id=PLATFORM_TENANT_ID,
        application_id=payload.application_id,
        name=payload.name,
        description=payload.description,
    )
    uow.commit()
    return _dataset_out(created)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: UUID, repo: EvalRepoDep) -> dict:
    """数据集详情；不存在或他租户一律 404。"""
    return _dataset_out(_require_dataset(repo, dataset_id))


@router.patch("/datasets/{dataset_id}")
def update_dataset(
    dataset_id: UUID, payload: DatasetUpdatePayload, repo: EvalRepoDep, uow: UowDep
) -> dict:
    if not repo.update_dataset(
        PLATFORM_TENANT_ID, dataset_id, name=payload.name, description=payload.description
    ):
        raise NotFoundError("评测数据集不存在")
    uow.commit()
    return _dataset_out(_require_dataset(repo, dataset_id))


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: UUID, repo: EvalRepoDep, uow: UowDep) -> None:
    """删除数据集（级联删用例；历史 eval_run 行由库内 FK CASCADE 收敛）。"""
    if not repo.delete_dataset(PLATFORM_TENANT_ID, dataset_id):
        raise NotFoundError("评测数据集不存在")
    uow.commit()


# ========== eval_case ==========
@router.get("/datasets/{dataset_id}/cases")
def list_cases(dataset_id: UUID, repo: EvalRepoDep) -> dict:
    _require_dataset(repo, dataset_id)
    items = repo.list_cases(PLATFORM_TENANT_ID, dataset_id)
    return {"items": [_case_out(row) for row in items]}


@router.post("/datasets/{dataset_id}/cases", status_code=status.HTTP_201_CREATED)
def add_case(dataset_id: UUID, payload: CasePayload, repo: EvalRepoDep, uow: UowDep) -> dict:
    """新增用例（position 自动追加到集尾）。"""
    _require_dataset(repo, dataset_id)
    if not str(payload.input.get("message") or "").strip() and not payload.input.get("images"):
        raise ValidationError("用例 input 至少包含 message 或 images 之一")
    created = repo.add_case(
        tenant_id=PLATFORM_TENANT_ID,
        dataset_id=dataset_id,
        input_data=payload.input,
        expected=payload.expected,
        expected_tool_calls=payload.expected_tool_calls,
    )
    uow.commit()
    return _case_out(created)


@router.post("/datasets/{dataset_id}/cases/from-run", status_code=status.HTTP_201_CREATED)
def capture_case_from_run(
    dataset_id: UUID, payload: CaptureCasePayload, repo: EvalRepoDep, uow: UowDep
) -> dict:
    """F18.2 冷启动主通道：run.input→case.input、当时终答→case.expected（可再编辑）。"""
    ds = _require_dataset(repo, dataset_id)
    run = RunRepository(uow.session).get_run(payload.run_id)
    if run is None or run["workflow_id"] != ds["application_id"]:
        # 限本数据集归属应用的 run：他应用/他租户 run 一律按不存在处理（批末 review#2）
        raise NotFoundError("运行记录不存在")
    if run.get("execute_status") != "success":
        raise ValidationError("只能从正常结束的运行捕获用例")
    raw_input = run.get("input") or {}
    # run.input 的生产形态是 {"input": 问句, "images": [...]}（GraphRuntime.ensure_run
    # 原样落 invoke 入参）；case.input 用 message 键（评测直调侧 _CaseInputRunner 读取）
    message = str(raw_input.get("input") or raw_input.get("message") or "")
    if not message and not raw_input.get("images"):
        raise ValidationError("运行入参为空，无可用问句或图片")
    case_input: dict[str, Any] = {"message": message}
    if raw_input.get("images"):
        case_input["images"] = raw_input["images"]
    # 无终答可预填时 expected 置 NULL（捕获后可人工补参考应答）
    expected = extract_answer_text(run.get("output")) or None
    created = repo.add_case(
        tenant_id=PLATFORM_TENANT_ID, dataset_id=dataset_id, input_data=case_input,
        expected=expected,
    )
    uow.commit()
    return _case_out(created)


@router.patch("/cases/{case_id}")
def update_case(case_id: UUID, payload: CasePayload, repo: EvalRepoDep, uow: UowDep) -> dict:
    if not str(payload.input.get("message") or "").strip() and not payload.input.get("images"):
        raise ValidationError("用例 input 至少包含 message 或 images 之一")
    if not repo.update_case(
        PLATFORM_TENANT_ID, case_id,
        input_data=payload.input,
        expected=payload.expected,
        expected_tool_calls=payload.expected_tool_calls,
    ):
        raise NotFoundError("用例不存在")
    uow.commit()
    updated = repo.get_case(PLATFORM_TENANT_ID, case_id)
    if updated is None:
        raise NotFoundError("用例不存在")
    return _case_out(updated)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: UUID, repo: EvalRepoDep, uow: UowDep) -> None:
    if not repo.delete_case(PLATFORM_TENANT_ID, case_id):
        raise NotFoundError("用例不存在")
    uow.commit()


# ========== eval_evaluator ==========
@router.get("/evaluators")
def list_evaluators(
    repo: EvalRepoDep,
    eval_type: Annotated[str | None, Query(alias="type", pattern="^(rule|llm_judge)$")] = None,
) -> dict:
    items = repo.list_evaluators(PLATFORM_TENANT_ID, type_=eval_type)
    return {"items": [_evaluator_out(row) for row in items]}


@router.post("/evaluators", status_code=status.HTTP_201_CREATED)
def create_evaluator(payload: EvaluatorPayload, repo: EvalRepoDep, uow: UowDep) -> dict:
    created = repo.create_evaluator(
        tenant_id=PLATFORM_TENANT_ID,
        name=payload.name,
        type_=payload.type,
        config=payload.config,
    )
    uow.commit()
    return _evaluator_out(created)


@router.patch("/evaluators/{evaluator_id}")
def update_evaluator(
    evaluator_id: UUID, payload: EvaluatorUpdatePayload, repo: EvalRepoDep, uow: UowDep
) -> dict:
    if not repo.update_evaluator(
        PLATFORM_TENANT_ID, evaluator_id,
        name=payload.name, type_=payload.type, config=payload.config,
    ):
        raise NotFoundError("评估器不存在")
    uow.commit()
    updated = repo.get_evaluator(PLATFORM_TENANT_ID, evaluator_id)
    if updated is None:
        raise NotFoundError("评估器不存在")
    return _evaluator_out(updated)


@router.delete("/evaluators/{evaluator_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator(evaluator_id: UUID, repo: EvalRepoDep, uow: UowDep) -> None:
    if not repo.delete_evaluator(PLATFORM_TENANT_ID, evaluator_id):
        raise NotFoundError("评估器不存在")
    uow.commit()


# ========== eval_run ==========
@router.post("/eval-runs", status_code=status.HTTP_201_CREATED)
def start_eval_run(
    payload: StartEvalRunPayload, repo: EvalRepoDep, uow: UowDep
) -> dict:
    """发起评测批：校验数据集/发布版本/评估器存在后落行并投递 worker。

    broker 不可达时批落 error 态可见、接口不炸（投递降级在 EvalRunService 内）。
    """
    ds = _require_dataset(repo, payload.dataset_id)
    snapshot = ApplicationRepository(uow.session).get_graph_version(
        ds["application_id"], payload.graph_version
    )
    if snapshot is None:
        raise ValidationError(f"应用不存在发布版本 {payload.graph_version}")
    for evaluator_id in payload.evaluator_ids:
        if repo.get_evaluator(PLATFORM_TENANT_ID, evaluator_id) is None:
            raise ValidationError(f"评估器 {evaluator_id} 不存在")
    service = EvalRunService(
        eval_repo=repo,
        run_repo=RunRepository(uow.session),
        runtime_factory=None,
        batch_task=eval_batch_task,
        commit_hook=uow.commit,
    )
    run_id = service.start_batch(
        tenant_id=PLATFORM_TENANT_ID,
        application_id=ds["application_id"],
        dataset_id=payload.dataset_id,
        graph_version=payload.graph_version,
        evaluator_ids=[str(eid) for eid in payload.evaluator_ids],
        concurrency=payload.concurrency,
    )
    return {"eval_run_id": str(run_id)}


@router.get("/eval-runs")
def list_eval_runs(
    repo: EvalRepoDep, application_id: UUID = Query(..., description="按应用查批任务列表")
) -> dict:
    items = repo.list_eval_runs(PLATFORM_TENANT_ID, application_id)
    return {"items": [_run_out(row) for row in items]}


@router.get("/eval-runs/diff")
def diff_eval_runs(
    run_a: Annotated[UUID, Query(...)],
    run_b: Annotated[UUID, Query(...)],
    repo: EvalRepoDep,
) -> dict:
    """两次批跑按 case 对齐（F18.5 回退清单：a=pass ∧ b≠pass 即回归）。"""
    run_a_row = _require_eval_run(repo, run_a)
    run_b_row = _require_eval_run(repo, run_b)
    if run_a_row["dataset_id"] != run_b_row["dataset_id"]:
        # 跨数据集对齐恒得 status_b=None，回退清单会静默失真（批末 review#5）
        raise ValidationError("两次评测批不属于同一数据集，diff 无意义")
    rows = repo.diff_results(PLATFORM_TENANT_ID, run_a, run_b)
    items = [
        {
            "case_id": str(row["case_id"]),
            "position": row["position"],
            "status_a": row["status_a"],
            "score_a": row["score_a"],
            "reason_a": row["reason_a"],
            "status_b": row["status_b"],
            "score_b": row["score_b"],
            "reason_b": row["reason_b"],
        }
        for row in rows
    ]
    return {"items": items}


@router.get("/eval-runs/{eval_run_id}")
def get_eval_run_detail(eval_run_id: UUID, repo: EvalRepoDep) -> dict:
    """报告页数据：批状态 + 逐 case 结果 + 汇总通过率（F18.5）。"""
    run = _require_eval_run(repo, eval_run_id)
    results = repo.list_results(PLATFORM_TENANT_ID, eval_run_id)
    total = len(results)
    counts = {"pass": 0, "fail": 0, "error": 0}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {
        "total": total,
        "passed": counts["pass"],
        "failed": counts["fail"],
        "errored": counts["error"],
        "pass_rate": (counts["pass"] / total) if total else 0.0,
    }
    return {
        "run": _run_out(run),
        "results": [_result_out(row) for row in results],
        "summary": summary,
    }


# ========== 质量摘要（挂在应用路径下，供应用详情"质量"页签消费） ==========
# 独立 router 而非嵌套进 /eval：路由聚合前缀会叠加，嵌套后路径会变成 /eval/apps/...
quality_router = APIRouter(prefix="/apps", tags=["eval-admin"], dependencies=[Depends(require_platform_admin)])


@quality_router.get("/{application_id}/quality/summary")
def quality_summary(
    application_id: UUID,
    repo: EvalRepoDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict:
    """F18.6 质量看板：最近完成批通过率 + 采样 7 日均分趋势 + 低分清单（飞轮入口）。

    days 窗口只约束 runtime_samples（持续流入需限窗）；评测批由人工发起、数量
    有限，计数与最近通过率取全量。低分清单行带 run_id，前端一键 from-run 转评测集。
    """
    completed_runs = [
        row for row in repo.list_eval_runs(PLATFORM_TENANT_ID, application_id)
        if row["status"] == "completed"
    ]
    latest_pass_rate: float | None = None
    if completed_runs:
        results = repo.list_results(PLATFORM_TENANT_ID, completed_runs[0]["id"])
        if results:
            passed = sum(1 for row in results if row["status"] == "pass")
            latest_pass_rate = passed / len(results)
    samples = repo.list_runtime_samples(application_id, days=days)
    scores = [row["score"] for row in samples if row.get("score") is not None]
    trend = _sample_trend(samples, days)
    low_items = [
        {
            "run_id": str(row["run_id"]),
            "question": _sample_question(row.get("run_input")),
            "status": row["status"],
            "score": row["score"],
            "reason": row["reason"],
            "created_at": _iso(row["created_at"]),
        }
        for row in samples
        if row.get("score") is not None and row["score"] <= _LOW_SCORE_THRESHOLD
    ][:_LOW_SCORE_LIST_LIMIT]
    return {
        "window_days": days,
        "eval_batches": {"count": len(completed_runs), "latest_pass_rate": latest_pass_rate},
        "runtime_samples": {
            "count": len(samples),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "low_score_count": sum(1 for value in scores if value <= _LOW_SCORE_THRESHOLD),
        },
        "trend": trend,
        "low_score_items": low_items,
    }


def _sample_trend(samples: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """按 UTC 日聚合采样判定为逐日均分序列（无样本日补零，旧→新升序）。

    桶区间（最旧桶日 00:00 起）与仓储窗口同口径（批末 review F1，见
    list_runtime_samples 注释），保证概览计数恒等于逐日桶之和。
    """
    today = datetime.now(UTC).date()
    buckets: dict[str, list[dict[str, Any]]] = {
        (today - timedelta(days=offset)).isoformat(): []
        for offset in range(days)
    }
    for row in samples:
        created = row["created_at"]
        if isinstance(created, datetime):
            key = created.astimezone(UTC).date().isoformat()
            if key in buckets:
                buckets[key].append(row)
    trend = []
    for date_key in sorted(buckets):
        day_rows = buckets[date_key]
        day_scores = [row["score"] for row in day_rows if row.get("score") is not None]
        trend.append(
            {
                "date": date_key,
                "count": len(day_rows),
                "avg_score": round(sum(day_scores) / len(day_scores), 2) if day_scores else None,
            }
        )
    return trend


def _sample_question(run_input: Any) -> str:
    """采样行问句预览：生产形态 {"input": 问句}，兼容 message 键（from-run 捕获同口径）。"""
    raw = run_input if isinstance(run_input, dict) else {}
    return str(raw.get("input") or raw.get("message") or "")
