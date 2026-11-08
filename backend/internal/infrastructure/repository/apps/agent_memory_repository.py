"""长期记忆仓储：agent_memory 表读写（M4 PRD F16.2/F16.3/F16.4）。

原生 SQL 风格对齐 conversation_repository；调用方（抽取管线/召回注入/管理面）
传入已鉴权的 tenant×app×user 作用域，仓储只负责按作用域读写，不做越权兜底。
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


class AgentMemoryRepository:
    """agent_memory 仓储：活跃记忆增删查、FIFO 容量归档、命中计数、幂等探测。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        user_id: UUID,
        kind: str,
        content: str,
        source_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """新增一条活跃记忆；kind 越界由 DB CHECK 约束拒绝（上游抽取管线已归一）。"""
        memory_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO agent_memory "
                "(id, tenant_id, application_id, user_id, kind, content, source_run_id, metadata) "
                "VALUES (:id, :tid, :aid, :uid, :kind, :content, :run_id, "
                "CAST(:metadata AS JSONB))"
            ),
            {
                "id": memory_id,
                "tid": tenant_id,
                "aid": application_id,
                "uid": user_id,
                "kind": kind,
                "content": content,
                "run_id": source_run_id,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return memory_id

    def get(self, memory_id: UUID) -> dict | None:
        row = self._session.execute(
            text("SELECT * FROM agent_memory WHERE id = :id"), {"id": memory_id}
        ).first()
        return _row_to_dict(row) if row else None

    def list_active(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        user_id: UUID,
        limit: int = 100,
    ) -> list[dict]:
        """按作用域取活跃记忆（时近倒序），供召回打分与抽取去重对照。"""
        rows = self._session.execute(
            text(
                "SELECT * FROM agent_memory "
                "WHERE tenant_id = :tid AND application_id = :aid AND user_id = :uid "
                "AND status = 'active' "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"tid": tenant_id, "aid": application_id, "uid": user_id, "limit": limit},
        ).all()
        return [_row_to_dict(r) for r in rows]

    def count_active(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        user_id: UUID,
    ) -> int:
        row = self._session.execute(
            text(
                "SELECT count(*) AS cnt FROM agent_memory "
                "WHERE tenant_id = :tid AND application_id = :aid AND user_id = :uid "
                "AND status = 'active'"
            ),
            {"tid": tenant_id, "aid": application_id, "uid": user_id},
        ).first()
        return int(row.cnt) if row else 0

    def archive_overflow(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        user_id: UUID,
        max_active: int,
    ) -> int:
        """容量收口（PRD F16.3）：活跃数超 max_active 时按最旧优先置 archived。

        先数后删两步非常量时间完成，并发写入最多多留/多挡一条，
        由下一轮抽取再收口，不做行锁。
        """
        total = self.count_active(
            tenant_id=tenant_id, application_id=application_id, user_id=user_id
        )
        overflow = total - max_active
        if overflow <= 0:
            return 0
        result = self._session.execute(
            text(
                "UPDATE agent_memory SET status = 'archived', updated_at = now() "
                "WHERE id IN ("
                "  SELECT id FROM agent_memory "
                "  WHERE tenant_id = :tid AND application_id = :aid AND user_id = :uid "
                "  AND status = 'active' "
                "  ORDER BY created_at ASC LIMIT :overflow"
                ")"
            ),
            {"tid": tenant_id, "aid": application_id, "uid": user_id, "overflow": overflow},
        )
        return cast("CursorResult[Any]", result).rowcount

    def update_content(self, memory_id: UUID, *, content: str, kind: str | None = None) -> bool:
        """合并管线 update 指令用：仅活跃条目可改写（archived 视为历史，不再变更）。"""
        result = self._session.execute(
            text(
                "UPDATE agent_memory SET content = :content, "
                "kind = COALESCE(:kind, kind), updated_at = now() "
                "WHERE id = :id AND status = 'active'"
            ),
            {"id": memory_id, "content": content, "kind": kind},
        )
        return cast("CursorResult[Any]", result).rowcount > 0

    def delete_scoped(
        self,
        memory_id: UUID,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID | None = None,
    ) -> bool:
        """用户管理面删除（F16.6）：作用域不匹配一律 0 行，防越权 IDOR。"""
        result = self._session.execute(
            text(
                "DELETE FROM agent_memory WHERE id = :id AND tenant_id = :tid "
                "AND user_id = :uid "
                "AND (CAST(:aid AS UUID) IS NULL OR application_id = CAST(:aid AS UUID))"
            ),
            {"id": memory_id, "tid": tenant_id, "uid": user_id, "aid": application_id},
        )
        return cast("CursorResult[Any]", result).rowcount > 0

    def delete_by_scope(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        user_id: UUID,
    ) -> int:
        """清空当前 user×app 全部记忆（F16.6 清空，物理删除满足隐私口径）。"""
        result = self._session.execute(
            text(
                "DELETE FROM agent_memory "
                "WHERE tenant_id = :tid AND application_id = :aid AND user_id = :uid"
            ),
            {"tid": tenant_id, "aid": application_id, "uid": user_id},
        )
        return cast("CursorResult[Any]", result).rowcount

    def search_for_admin(
        self,
        *,
        application_id: UUID,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        status: str = "active",
        keyword: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """管理端排障检索（M4 PRD F16.7）：应用维度 + 可选租户/用户/状态/正文关键词。

        返回（当页行, 总数）；keyword 用 ILIKE 子串匹配，% _ 反斜杠按字面转义。
        仅供平台管理员排障，作用域收敛由调用方（路由鉴权）保证。
        """
        conditions = ["application_id = :aid"]
        params: dict[str, Any] = {"aid": application_id, "limit": limit, "offset": offset}
        if tenant_id is not None:
            conditions.append("tenant_id = :tid")
            params["tid"] = tenant_id
        if user_id is not None:
            conditions.append("user_id = :uid")
            params["uid"] = user_id
        if status != "all":
            conditions.append("status = :status")
            params["status"] = status
        if keyword:
            escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("content ILIKE :kw")
            params["kw"] = f"%{escaped}%"
        where = " AND ".join(conditions)
        rows = self._session.execute(
            text(
                f"SELECT * FROM agent_memory WHERE {where} "
                "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        total = self._session.execute(
            text(f"SELECT count(*) AS cnt FROM agent_memory WHERE {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).first()
        return [_row_to_dict(r) for r in rows], int(total.cnt) if total else 0

    def bump_hit_count(self, memory_ids: list[UUID]) -> int:
        """召回命中计数自增（F16.4，best-effort）；不动 updated_at，避免污染时近打分。"""
        if not memory_ids:
            return 0
        result = self._session.execute(
            text(
                "UPDATE agent_memory SET hit_count = hit_count + 1 "
                "WHERE id = ANY(CAST(:ids AS UUID[]))"
            ),
            {"ids": [str(memory_id) for memory_id in memory_ids]},
        )
        return cast("CursorResult[Any]", result).rowcount

    def exists_by_source_run(self, source_run_id: UUID) -> bool:
        """抽取幂等（F16.3）：同一 run 已抽取过则跳过，防 Celery 重试重复沉淀。"""
        row = self._session.execute(
            text("SELECT 1 FROM agent_memory WHERE source_run_id = :run_id LIMIT 1"),
            {"run_id": source_run_id},
        ).first()
        return row is not None
