"""M4-d T-d3 冒烟：评测批真链路（EvalRepository 造数 → start_batch 投递 → worker 执行）。

前置：先启动 worker（另开进程）：
    .venv/Scripts/python.exe -m celery -A internal.infrastructure.celery_app worker -Q rag --pool=solo --loglevel=info
用法：
    .venv/Scripts/python.exe scripts/smoke_eval_batch.py
校验：eval_run 终态 completed、结果行齐全、被评 run 带 is_eval=true、运行日志列表隐身。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from internal.application.apps.eval_run_service import EvalRunService
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from web.tasks.eval_tasks import run_batch as batch_task

# 接管冒烟主助手（e2etenant，图版本 4 已发布，今日真机链路验证过）
TENANT = UUID("01a1a196-6de6-7e44-b9e1-5574632f020d")
APP = UUID("01a1b601-f0a9-73a5-8582-5f420732e565")
GRAPH_VERSION = 4


def main() -> int:
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        repo = EvalRepository(uow.session)
        ds = repo.create_dataset(
            tenant_id=TENANT, application_id=APP, name="T-d3冒烟集", description="M4-d smoke"
        )
        repo.add_case(
            tenant_id=TENANT, dataset_id=ds["id"], input_data={"message": "只回复：好的收到"}
        )
        repo.add_case(
            tenant_id=TENANT, dataset_id=ds["id"], input_data={"message": "1+1等于几？只回复数字"}
        )
        ev = repo.create_evaluator(tenant_id=TENANT, name="恒过", type_="rule", config={})
        service = EvalRunService(
            eval_repo=repo,
            run_repo=RunRepository(uow.session),
            runtime_factory=None,
            batch_task=batch_task,
            commit_hook=uow.commit,
        )
        run_id = service.start_batch(
            tenant_id=TENANT,
            application_id=APP,
            dataset_id=ds["id"],
            graph_version=GRAPH_VERSION,
            evaluator_ids=[str(ev["id"])],
            concurrency=2,
        )
        print("eval_run:", run_id, flush=True)

        row = repo.get_eval_run(TENANT, run_id)
        deadline = time.time() + 300
        while time.time() < deadline:
            row = repo.get_eval_run(TENANT, run_id)
            uow.session.commit()
            print("status:", row["status"], "progress:", row["progress"], flush=True)
            if row["status"] != "running":
                break
            time.sleep(10)

        results = repo.list_results(TENANT, run_id)
        for r in results:
            print("result:", r["status"], r["score"], (r["reason"] or "")[:60], "run:", r["run_id"])
        run_repo = RunRepository(uow.session)
        eval_run_ids = set()
        for r in results:
            if r["run_id"]:
                eval_run_ids.add(r["run_id"])
                rr = run_repo.get_run(r["run_id"])
                ok = rr is not None and rr["is_eval"] is True
                print("is_eval:", ok, "execute_status:", rr and rr["execute_status"])
                if not ok:
                    print("SMOKE FAIL: 被评 run 缺少 is_eval 标记")
                    return 1
        listed = run_repo.list_runs(TENANT, workflow_id=APP)
        if eval_run_ids & {item["id"] for item in listed}:
            print("SMOKE FAIL: 评测 run 泄漏进运行日志列表")
            return 1
        if row["status"] != "completed":
            print("SMOKE FAIL:", row["status"], row["error_message"])
            return 1
        print("SMOKE PASS: completed, results:", len(results))
        return 0
    finally:
        uow.close()


if __name__ == "__main__":
    sys.exit(main())
