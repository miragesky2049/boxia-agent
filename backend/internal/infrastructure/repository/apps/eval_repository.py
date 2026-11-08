"""M4-d PRD F18.1：评测五表仓储（eval_dataset/eval_case/eval_evaluator/eval_run/eval_result）。

裸 SQL 口径对齐 run/agent_memory 仓储；tenant_id 作为查询硬条件（防 IDOR），
updated_at 由仓储显式回写（对齐 0077 建表注释）。
"""

from __future__ import annotations

import json
from typing import Any
from typing import cast as _cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


def _affected(result: Any) -> bool:
    """UPDATE/DELETE 行数判定，口径对齐 run_repository 的 CursorResult cast。"""
    return _cast("CursorResult[Any]", result).rowcount > 0


class EvalRepository:
    """评测仓储：数据集/用例/评估器 CRUD、批任务生命周期、结果批量写与 diff。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== eval_dataset ==========
    def create_dataset(
        self, *, tenant_id: UUID, application_id: UUID, name: str, description: str = ""
    ) -> dict:
        dataset_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO eval_dataset (id, tenant_id, application_id, name, description) "
                "VALUES (:id, :tid, :aid, :name, :description)"
            ),
            {
                "id": dataset_id,
                "tid": tenant_id,
                "aid": application_id,
                "name": name,
                "description": description,
            },
        )
        return self.get_dataset(tenant_id, dataset_id) or {"id": dataset_id, "name": name}

    def list_datasets(self, tenant_id: UUID, application_id: UUID | None = None) -> list[dict]:
        sql = (
            "SELECT id, application_id, name, description, created_at, updated_at "
            "FROM eval_dataset WHERE tenant_id = :tid"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if application_id is not None:
            sql += " AND application_id = :aid"
            params["aid"] = application_id
        sql += " ORDER BY created_at DESC"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    def get_dataset(self, tenant_id: UUID, dataset_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, application_id, name, description, created_at, updated_at "
                "FROM eval_dataset WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": dataset_id},
        ).one_or_none()
        return dict(row._mapping) if row else None

    def update_dataset(
        self, tenant_id: UUID, dataset_id: UUID, *, name: str, description: str
    ) -> bool:
        result = self._session.execute(
            text(
                "UPDATE eval_dataset SET name = :name, description = :description, "
                "updated_at = now() WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": dataset_id, "name": name, "description": description},
        )
        return _affected(result)

    def delete_dataset(self, tenant_id: UUID, dataset_id: UUID) -> bool:
        result = self._session.execute(
            text("DELETE FROM eval_dataset WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": dataset_id},
        )
        return _affected(result)

    # ========== eval_case ==========
    def add_case(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        input_data: dict[str, Any],
        expected: str | None = None,
        expected_tool_calls: dict[str, Any] | None = None,
    ) -> dict:
        case_id = new_uuid()
        # position 追加语义：当前集内 max+1（批跑按序展示、diff 按 case 对齐不依赖它）
        self._session.execute(
            text(
                "INSERT INTO eval_case (id, tenant_id, dataset_id, input, expected, "
                "expected_tool_calls, position) "
                "SELECT :id, :tid, :dsid, CAST(:input AS JSONB), :expected, "
                "CAST(:tool_calls AS JSONB), COALESCE(MAX(position), -1) + 1 "
                "FROM eval_case WHERE dataset_id = :dsid"
            ),
            {
                "id": case_id,
                "tid": tenant_id,
                "dsid": dataset_id,
                "input": json.dumps(input_data),
                "expected": expected,
                "tool_calls": json.dumps(expected_tool_calls) if expected_tool_calls else None,
            },
        )
        return self.get_case(tenant_id, case_id) or {"id": case_id}

    def list_cases(self, tenant_id: UUID, dataset_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, dataset_id, input, expected, expected_tool_calls, position, "
                "created_at, updated_at "
                "FROM eval_case WHERE tenant_id = :tid AND dataset_id = :dsid "
                "ORDER BY position"
            ),
            {"tid": tenant_id, "dsid": dataset_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def get_case(self, tenant_id: UUID, case_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, dataset_id, input, expected, expected_tool_calls, position "
                "FROM eval_case WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": case_id},
        ).one_or_none()
        return dict(row._mapping) if row else None

    def update_case(
        self,
        tenant_id: UUID,
        case_id: UUID,
        *,
        input_data: dict[str, Any],
        expected: str | None = None,
        expected_tool_calls: dict[str, Any] | None = None,
    ) -> bool:
        result = self._session.execute(
            text(
                "UPDATE eval_case SET input = CAST(:input AS JSONB), expected = :expected, "
                "expected_tool_calls = CAST(:tool_calls AS JSONB), updated_at = now() "
                "WHERE tenant_id = :tid AND id = :id"
            ),
            {
                "tid": tenant_id,
                "id": case_id,
                "input": json.dumps(input_data),
                "expected": expected,
                "tool_calls": json.dumps(expected_tool_calls) if expected_tool_calls else None,
            },
        )
        return _affected(result)

    def delete_case(self, tenant_id: UUID, case_id: UUID) -> bool:
        result = self._session.execute(
            text("DELETE FROM eval_case WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": case_id},
        )
        return _affected(result)

    # ========== eval_evaluator ==========
    def create_evaluator(
        self, *, tenant_id: UUID, name: str, type_: str, config: dict[str, Any]
    ) -> dict:
        evaluator_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO eval_evaluator (id, tenant_id, name, type, config) "
                "VALUES (:id, :tid, :name, :type, CAST(:config AS JSONB))"
            ),
            {
                "id": evaluator_id,
                "tid": tenant_id,
                "name": name,
                "type": type_,
                "config": json.dumps(config or {}),
            },
        )
        return self.get_evaluator(tenant_id, evaluator_id) or {"id": evaluator_id, "name": name}

    def list_evaluators(self, tenant_id: UUID, type_: str | None = None) -> list[dict]:
        sql = (
            "SELECT id, name, type, config, created_at, updated_at "
            "FROM eval_evaluator WHERE tenant_id = :tid"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if type_ is not None:
            sql += " AND type = :type"
            params["type"] = type_
        sql += " ORDER BY created_at"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    def get_evaluator(self, tenant_id: UUID, evaluator_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, name, type, config, created_at, updated_at "
                "FROM eval_evaluator WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": evaluator_id},
        ).one_or_none()
        return dict(row._mapping) if row else None

    def update_evaluator(
        self, tenant_id: UUID, evaluator_id: UUID, *, name: str, type_: str, config: dict[str, Any]
    ) -> bool:
        result = self._session.execute(
            text(
                "UPDATE eval_evaluator SET name = :name, type = :type, "
                "config = CAST(:config AS JSONB), updated_at = now() "
                "WHERE tenant_id = :tid AND id = :id"
            ),
            {
                "tid": tenant_id,
                "id": evaluator_id,
                "name": name,
                "type": type_,
                "config": json.dumps(config or {}),
            },
        )
        return _affected(result)

    def delete_evaluator(self, tenant_id: UUID, evaluator_id: UUID) -> bool:
        result = self._session.execute(
            text("DELETE FROM eval_evaluator WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": evaluator_id},
        )
        return _affected(result)

    # ========== eval_run ==========
    def insert_eval_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        application_id: UUID,
        graph_version: int,
        dataset_id: UUID,
        evaluator_ids: list[str],
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO eval_run (id, tenant_id, application_id, graph_version, "
                "dataset_id, evaluator_ids, status) VALUES "
                "(:id, :tid, :aid, :version, :dsid, CAST(:evaluator_ids AS JSONB), 'running')"
            ),
            {
                "id": run_id,
                "tid": tenant_id,
                "aid": application_id,
                "version": graph_version,
                "dsid": dataset_id,
                "evaluator_ids": json.dumps(evaluator_ids),
            },
        )

    def update_eval_run(
        self,
        run_id: UUID,
        *,
        status: str | None = None,
        progress: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        # 动态 SET：批任务心跳只回写 progress，终态回写 status/usage/error
        sets: list[str] = []
        params: dict[str, Any] = {"id": run_id}
        if status is not None:
            sets.append("status = :status")
            params["status"] = status
        if progress is not None:
            sets.append("progress = CAST(:progress AS JSONB)")
            params["progress"] = json.dumps(progress)
        if usage is not None:
            sets.append("usage = CAST(:usage AS JSONB)")
            params["usage"] = json.dumps(usage)
        if error_message is not None:
            sets.append("error_message = :error")
            params["error"] = error_message
        if not sets:
            return
        sets.append("updated_at = now()")
        self._session.execute(text(f"UPDATE eval_run SET {', '.join(sets)} WHERE id = :id"), params)

    def get_eval_run(self, tenant_id: UUID, run_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, application_id, graph_version, dataset_id, evaluator_ids, "
                "status, progress, usage, error_message, created_at, updated_at "
                "FROM eval_run WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": run_id},
        ).one_or_none()
        return dict(row._mapping) if row else None

    def list_eval_runs(self, tenant_id: UUID, application_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, graph_version, dataset_id, evaluator_ids, status, progress, usage, "
                "error_message, created_at, updated_at "
                "FROM eval_run WHERE tenant_id = :tid AND application_id = :aid "
                "ORDER BY created_at DESC"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    # ========== eval_result ==========
    def insert_results(self, rows: list[dict[str, Any]]) -> None:
        """批量写判定结果（批任务逐 case 收口后一次落库，减少往返）。"""
        for row in rows:
            self._session.execute(
                text(
                    "INSERT INTO eval_result (id, tenant_id, eval_run_id, run_id, case_id, "
                    "status, score, reason, judge_usage, source) VALUES "
                    "(:id, :tid, :eval_run_id, :run_id, :case_id, :status, :score, :reason, "
                    "CAST(:judge_usage AS JSONB), :source)"
                ),
                {
                    "id": row["id"],
                    "tid": row["tenant_id"],
                    "eval_run_id": row.get("eval_run_id"),
                    "run_id": row.get("run_id"),
                    "case_id": row.get("case_id"),
                    "status": row["status"],
                    "score": row.get("score"),
                    "reason": row.get("reason") or "",
                    "judge_usage": json.dumps(row["judge_usage"])
                    if row.get("judge_usage")
                    else None,
                    "source": row["source"],
                },
            )

    def has_runtime_sample(self, run_id: UUID) -> bool:
        """采样幂等探测（T-d8）：同一 run 只落一条 runtime_sample 判定行，
        任务重投（acks_late 中途被杀等）不再重复调 judge、不重复计费。"""
        row = self._session.execute(
            text(
                "SELECT 1 FROM eval_result WHERE run_id = :rid AND source = 'runtime_sample' LIMIT 1"
            ),
            {"rid": run_id},
        ).one_or_none()
        return row is not None

    def delete_results(self, eval_run_id: UUID) -> None:
        """批重放前置清理：删本批已落结果行（task_acks_late 中途被杀重投场景，批末 review#1）。"""
        self._session.execute(
            text("DELETE FROM eval_result WHERE eval_run_id = :rid"), {"rid": eval_run_id}
        )

    def list_results(self, tenant_id: UUID, eval_run_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, run_id, case_id, status, score, reason, judge_usage, source, "
                "created_at FROM eval_result "
                "WHERE tenant_id = :tid AND eval_run_id = :rid ORDER BY created_at"
            ),
            {"tid": tenant_id, "rid": eval_run_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def diff_results(self, tenant_id: UUID, run_a_id: UUID, run_b_id: UUID) -> list[dict]:
        """两次 eval_run 按 case 对齐（F18.5 回退清单：消费方按 a=pass ∧ b≠pass 过滤）。"""
        rows = self._session.execute(
            text(
                "SELECT c.id AS case_id, c.position, "
                "a.status AS status_a, a.score AS score_a, a.reason AS reason_a, "
                "b.status AS status_b, b.score AS score_b, b.reason AS reason_b "
                "FROM eval_case c "
                "JOIN eval_run r ON r.id = :ra AND c.dataset_id = r.dataset_id "
                "LEFT JOIN eval_result a ON a.case_id = c.id AND a.eval_run_id = :ra "
                "LEFT JOIN eval_result b ON b.case_id = c.id AND b.eval_run_id = :rb "
                "WHERE c.tenant_id = :tid "
                "ORDER BY c.position"
            ),
            {"tid": tenant_id, "ra": run_a_id, "rb": run_b_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def list_runtime_samples(self, application_id: UUID, *, days: int) -> list[dict]:
        """看板数据源（F18.6）：近 N 天 runtime_sample 判定，JOIN run 归因到应用。

        T-d9 可见性修复：采样行的 eval_result.tenant_id 是对话租户（worker 按
        run.tenant 落库），端点消费方为平台管理员且按应用归因（workflow_id 全局
        唯一），故不沿用平台租户过滤——加了它线上采样在看板上恒不可见。
        run_input 供低分清单展示问句预览（转评测集入口的判读依据）。

        批末 review F1：窗口按 UTC 日历日取（起点=最旧桶日 00:00 起算），与
        quality/summary 的 trend 日桶同口径——若用滚动窗口（now - N 天），
        最旧桶日前一天尾段样本会进概览指标却不进任何日桶，sum(trend.count)
        恒小于 runtime_samples.count，边界样本静默错位。days >= 1（端点校验）。
        """
        rows = self._session.execute(
            text(
                "SELECT r.id AS run_id, er.status, er.score, er.reason, er.judge_usage, "
                "er.created_at, r.input AS run_input "
                "FROM eval_result er JOIN run r ON r.id = er.run_id "
                "WHERE r.workflow_id = :aid "
                "AND er.source = 'runtime_sample' "
                "AND er.created_at >= (date_trunc('day', now() AT TIME ZONE 'UTC') "
                "AT TIME ZONE 'UTC') - make_interval(days => :days - 1) "
                "ORDER BY er.created_at DESC"
            ),
            {"aid": application_id, "days": days},
        ).all()
        return [dict(r._mapping) for r in rows]
