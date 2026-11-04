"""授权相关仓储：复用现有表 + 新建 application_apply。

- tenant_application_instance → 授权记录（复用）
- application_apply → 申请单（新建）
- audit_logs → 审计日志（复用）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class AuthRepository:
    """授权相关仓储。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== tenant_application_instance（授权记录） ==========
    def find_active_grant(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """鉴权查询：tenant+app 下当前 ACTIVE 且在有效期内的单条记录。"""
        now = datetime.utcnow()
        stmt = text("""
            SELECT * FROM tenant_application_instance
            WHERE tenant_id = :tid
              AND application_id = :aid
              AND status = 'active'
              AND (start_time IS NULL OR start_time <= :now)
              AND (expire_time IS NULL OR expire_time > :now)
            LIMIT 1
        """)
        row = self._session.execute(
            stmt,
            {
                "tid": tenant_id,
                "aid": application_id,
                "now": now,
            },
        ).first()
        return dict(row._mapping) if row else None

    def exists_active_grant(self, tenant_id: UUID, application_id: UUID) -> bool:
        """MVP 校验：是否已存在 ACTIVE 授权。"""
        stmt = text("""
            SELECT id FROM tenant_application_instance
            WHERE tenant_id = :tid
              AND application_id = :aid
              AND status = 'active'
            LIMIT 1
        """)
        return (
            self._session.execute(stmt, {"tid": tenant_id, "aid": application_id}).first()
            is not None
        )

    def get_grant(self, instance_id: UUID) -> dict | None:
        stmt = text("SELECT * FROM tenant_application_instance WHERE id = :id")
        row = self._session.execute(stmt, {"id": instance_id}).first()
        return dict(row._mapping) if row else None

    def list_grants_by_tenant(self, tenant_id: UUID) -> list[dict]:
        """租户控制台"我的应用"：全部非 revoked 记录。"""
        stmt = text("""
            SELECT i.*, a.name, a.description, a.avatar_url
            FROM tenant_application_instance i
            JOIN application a ON a.id = i.application_id
            WHERE i.tenant_id = :tid AND i.status != 'revoked'
            ORDER BY i.created_at DESC
        """)
        rows = self._session.execute(stmt, {"tid": tenant_id}).all()
        return [dict(r._mapping) for r in rows]

    def list_wait_effective(self, now: datetime) -> list[dict]:
        """定时任务：扫描 WAIT_EFFECT 且 start_time <= now。"""
        stmt = text("""
            SELECT * FROM tenant_application_instance
            WHERE status = 'wait_effect' AND start_time <= :now
        """)
        rows = self._session.execute(stmt, {"now": now}).all()
        return [dict(r._mapping) for r in rows]

    def list_expired(self, now: datetime) -> list[dict]:
        """定时任务：扫描 ACTIVE 且 expire_time <= now。"""
        stmt = text("""
            SELECT * FROM tenant_application_instance
            WHERE status = 'active' AND expire_time IS NOT NULL AND expire_time <= :now
        """)
        rows = self._session.execute(stmt, {"now": now}).all()
        return [dict(r._mapping) for r in rows]

    def create_grant(self, data: dict[str, Any]) -> UUID:
        """新增授权记录。"""
        instance_id = new_uuid()
        data["id"] = instance_id
        # psycopg3 不能直接适配 dict，JSONB 写入统一序列化为字符串后 CAST（与权益仓储同法）
        data["quota_json"] = json.dumps(data.get("quota_json") or {}, ensure_ascii=False)
        self._session.execute(
            text("""
            INSERT INTO tenant_application_instance
                (id, tenant_id, application_id, status, source, auth_source, auth_type,
                 contract_no, quota_json, start_time, expire_time, apply_id, remark,
                 granted_by, granted_at)
            VALUES
                (:id, :tenant_id, :application_id, :status, :source, :auth_source, :auth_type,
                 :contract_no, CAST(:quota_json AS JSONB), :start_time, :expire_time, :apply_id, :remark,
                 :granted_by, :granted_at)
        """),
            data,
        )
        return instance_id

    def update_grant_status(self, instance_id: UUID, status: str) -> None:
        self._session.execute(
            text("""
            UPDATE tenant_application_instance
            SET status = :status, updated_at = NOW()
            WHERE id = :id
        """),
            {"id": instance_id, "status": status},
        )

    # ========== application_apply（申请单） ==========
    def get_apply(self, apply_id: UUID) -> dict | None:
        stmt = text("SELECT * FROM application_apply WHERE id = :id")
        row = self._session.execute(stmt, {"id": apply_id}).first()
        return dict(row._mapping) if row else None

    def create_apply(self, data: dict[str, Any]) -> UUID:
        apply_id = new_uuid()
        data["id"] = apply_id
        self._session.execute(
            text("""
            INSERT INTO application_apply
                (id, tenant_id, application_id, apply_type, status, expect_text,
                 contact, sales_user_id, created_by)
            VALUES
                (:id, :tenant_id, :application_id, :apply_type, :status, :expect_text,
                 :contact, :sales_user_id, :created_by)
        """),
            data,
        )
        return apply_id

    def list_apply_by_tenant(self, tenant_id: UUID) -> list[dict]:
        """租户控制台"我的申请记录"。"""
        stmt = text("""
            SELECT ap.*, a.name as application_name
            FROM application_apply ap
            JOIN application a ON a.id = ap.application_id
            WHERE ap.tenant_id = :tid
            ORDER BY ap.created_at DESC
        """)
        rows = self._session.execute(stmt, {"tid": tenant_id}).all()
        return [dict(r._mapping) for r in rows]

    def list_apply_by_sales(self, sales_user_id: UUID) -> list[dict]:
        """销售工作台：归属自己的申请单。"""
        stmt = text("""
            SELECT ap.*, a.name as application_name
            FROM application_apply ap
            JOIN application a ON a.id = ap.application_id
            WHERE ap.sales_user_id = :sid
            ORDER BY ap.created_at DESC
        """)
        rows = self._session.execute(stmt, {"sid": sales_user_id}).all()
        return [dict(r._mapping) for r in rows]

    def list_pass_pending_apply(self) -> list[dict]:
        """运营筛选：状态=PASS，待关联开通授权。"""
        stmt = text("""
            SELECT ap.*, a.name as application_name
            FROM application_apply ap
            JOIN application a ON a.id = ap.application_id
            WHERE ap.status = 'PASS'
            ORDER BY ap.updated_at DESC
        """)
        rows = self._session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    def list_pending_applies(self) -> list[dict]:
        """运营工作台：待审核队列（SUBMITTED / HANDLING）。"""
        stmt = text("""
            SELECT ap.*, a.name as application_name,
                   u.username as sales_username
            FROM application_apply ap
            JOIN application a ON a.id = ap.application_id
            LEFT JOIN users u ON u.id = ap.sales_user_id
            WHERE ap.status IN ('SUBMITTED', 'HANDLING')
            ORDER BY ap.created_at ASC
        """)
        rows = self._session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    def get_latest_apply(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """查某租户对某应用最近一条申请单状态（市场详情页用）。"""
        stmt = text("""
            SELECT * FROM application_apply
            WHERE tenant_id = :tid AND application_id = :aid
            ORDER BY created_at DESC LIMIT 1
        """)
        row = self._session.execute(
            stmt,
            {
                "tid": tenant_id,
                "aid": application_id,
            },
        ).first()
        return dict(row._mapping) if row else None

    def ops_dashboard_stats(self) -> dict[str, Any]:
        """运营仪表盘统计：各状态申请数 + 活跃授权数。"""
        apply_row = self._session.execute(
            text("""
            SELECT
                COUNT(*) FILTER (WHERE status IN ('SUBMITTED','HANDLING')) AS pending_count,
                COUNT(*) FILTER (WHERE status = 'PASS') AS pass_pending_count,
                COUNT(*) FILTER (WHERE status = 'FINISH') AS finished_count,
                COUNT(*) FILTER (WHERE status = 'REJECT') AS rejected_count,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS last_7d_count
            FROM application_apply
        """)
        ).first()
        grant_row = self._session.execute(
            text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'active') AS active_grants,
                COUNT(*) FILTER (WHERE status = 'wait_effect') AS wait_effect_grants,
                COUNT(*) FILTER (WHERE status = 'expired') AS expired_grants
            FROM tenant_application_instance
        """)
        ).first()
        result: dict[str, Any] = {}
        if apply_row:
            result.update(dict(apply_row._mapping))
        if grant_row:
            result.update(dict(grant_row._mapping))
        return result

    def update_apply_status(
        self,
        apply_id: UUID,
        status: str,
        audit_msg: str = "",
        contract_no: str = "",
    ) -> None:
        self._session.execute(
            text("""
            UPDATE application_apply
            SET status = :status,
                audit_msg = CASE WHEN :audit_msg != '' THEN :audit_msg ELSE audit_msg END,
                contract_no = CASE WHEN :contract_no != '' THEN :contract_no ELSE contract_no END,
                updated_at = NOW()
            WHERE id = :id
        """),
            {"id": apply_id, "status": status, "audit_msg": audit_msg, "contract_no": contract_no},
        )

    def claim_apply(self, apply_id: UUID, sales_user_id: UUID) -> bool:
        """CAS 认领：仅仍处于 SUBMITTED 的行被更新，返回是否认领成功。

        并发第二人认领时 rowcount=0，避免读-改-写竞态下覆盖他人归属。
        """
        result = cast(
            CursorResult,
            self._session.execute(
                text("""
            UPDATE application_apply
            SET status = 'HANDLING', sales_user_id = :uid, updated_at = NOW()
            WHERE id = :id AND status = 'SUBMITTED'
        """),
                {"id": apply_id, "uid": sales_user_id},
            ),
        )
        return result.rowcount == 1

    # ========== audit_logs（审计日志） ==========
    def append_audit_log(self, data: dict[str, Any]) -> None:
        """复用 audit_logs 表写授权审计日志。"""
        import json as _json

        data = {**data, "id": new_uuid()}
        detail = data.get("detail")
        if not isinstance(detail, str):
            data["detail"] = _json.dumps(detail, ensure_ascii=False, default=str)
        self._session.execute(
            text("""
            INSERT INTO audit_logs
                (id, tenant_id, actor_id, actor_username, action, resource_type,
                 resource_id, detail)
            VALUES
                (:id, :tenant_id, :actor_id, :actor_username, :action, :resource_type,
                 :resource_id, CAST(:detail AS JSONB))
        """),
            data,
        )
