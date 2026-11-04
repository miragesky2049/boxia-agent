"""权益仓储实现：统一读写 tenant_application_instance（app）与 tenant_resource_entitlement（资源）。

只依赖 SQLAlchemy Core / text，不 import application 层（DDD 依赖方向：infra → domain）。
读侧 status 统一经 effective_status 按 [start, expire) 时间重算（D-3），
不依赖 Celery 任务把 wait_effect/expired 刷成持久值。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.entity.entitlement import (
    OBJECT_TYPE_APP,
    EntitlementItem,
    EntitlementView,
    effective_status,
)
from internal.infrastructure.id.uuid7 import new_uuid

# 两套存储的字段并集在 SQL 层对齐成同构列，Python 侧只处理一份映射
_LIST_SQL_BASE = """
    SELECT e.object_type, e.object_id, e.name, e.status, e.auth_source, e.auth_type,
           e.start_time, e.expire_time, e.quota, e.remark, e.granted_at, e.is_deprecated
    FROM (
        SELECT 'app' AS object_type, i.application_id AS object_id, a.name AS name,
               i.status, i.auth_source, i.auth_type, i.start_time, i.expire_time,
               COALESCE(i.quota_json, '{}'::jsonb) AS quota, i.remark, i.granted_at,
               FALSE AS is_deprecated
        FROM tenant_application_instance i
        JOIN application a ON a.id = i.application_id
        WHERE i.tenant_id = :tid
        UNION ALL
        SELECT r.type, g.resource_id, r.name,
               g.status, g.auth_source, g.auth_type, g.start_time, g.expire_time,
               COALESCE(g.quota_json, '{}'::jsonb), COALESCE(g.remark, ''), g.granted_at,
               r.is_deprecated
        FROM tenant_resource_entitlement g
        JOIN resource r ON r.id = g.resource_id
        WHERE g.tenant_id = :tid
    ) e
"""


class EntitlementRepository:
    """结构性满足 EntitlementRepositoryProtocol 的 PostgreSQL 实现。"""

    def __init__(self, session: Session, grace_days: int = 0):
        self._session = session
        # 宽限期读侧口径（P3-11），与流转任务的 settings 同源装配
        self._grace_days = grace_days

    # ========== 读侧 ==========
    def list_by_tenant(
        self,
        tenant_id,
        object_type: str | None,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EntitlementView], int]:
        filters, params = self._filters(object_type, status, keyword)
        params["tid"] = tenant_id
        total = self._session.execute(
            text(f"SELECT count(*) FROM ({_LIST_SQL_BASE}{filters}) c"), params
        ).scalar_one()
        params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
        rows = self._session.execute(
            text(
                f"{_LIST_SQL_BASE}{filters} ORDER BY e.granted_at DESC NULLS LAST, e.object_id "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        return [self._to_view(row) for row in rows], int(total)

    def get(self, tenant_id, object_type: str, object_id) -> EntitlementView | None:
        filters, params = self._filters(object_type, None, None)
        params.update({"tid": tenant_id, "oid": object_id})
        filters += " AND e.object_id = :oid"
        row = self._session.execute(text(f"{_LIST_SQL_BASE}{filters} LIMIT 1"), params).first()
        return self._to_view(row) if row else None

    def list_tenants_by_object(
        self, object_type: str, object_id, page: int, page_size: int
    ) -> tuple[list[dict], int]:
        if object_type == OBJECT_TYPE_APP:
            base = """
                FROM tenant_application_instance e
                JOIN tenants t ON t.id = e.tenant_id
                WHERE e.application_id = :oid
            """
        else:
            base = """
                FROM tenant_resource_entitlement e
                JOIN resource r ON r.id = e.resource_id
                JOIN tenants t ON t.id = e.tenant_id
                WHERE e.resource_id = :oid AND r.type = :otype
            """
        params: dict[str, Any] = {"oid": object_id, "otype": object_type}
        total = self._session.execute(text(f"SELECT count(*) {base}"), params).scalar_one()
        params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
        select_cols = "e.tenant_id, t.name AS tenant_name, e.status, e.auth_source, e.granted_at"
        rows = self._session.execute(
            text(
                f"SELECT {select_cols} {base} ORDER BY e.granted_at DESC NULLS LAST "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        return [dict(row._mapping) for row in rows], int(total)

    def describe_object(self, object_type: str, object_id) -> dict | None:
        if object_type == OBJECT_TYPE_APP:
            row = self._session.execute(
                text("SELECT id, name, FALSE AS is_deprecated FROM application WHERE id = :oid"),
                {"oid": object_id},
            ).first()
        else:
            row = self._session.execute(
                text(
                    "SELECT id, name, is_deprecated FROM resource WHERE id = :oid AND type = :otype"
                ),
                {"oid": object_id, "otype": object_type},
            ).first()
        return dict(row._mapping) if row else None

    def affected_role_grants(self, tenant_id, object_type: str, object_id) -> list[dict]:
        rows = self._session.execute(
            text(
                """
                SELECT rg.role_id, ro.name AS role_name, rg.subject_type
                FROM resource_grants rg
                JOIN roles ro ON ro.id = rg.role_id
                WHERE rg.tenant_id = :tid AND rg.resource_type = :otype AND rg.resource_id = :oid
                ORDER BY ro.name
                """
            ),
            {"tid": tenant_id, "otype": object_type, "oid": object_id},
        ).all()
        return [dict(row._mapping) for row in rows]

    # ========== 写侧 ==========
    def grant(
        self,
        tenant_id,
        item: EntitlementItem,
        *,
        auth_source: str,
        auth_type: str,
        start_time: datetime | None,
        expire_time: datetime | None,
        quota: dict[str, Any],
        remark: str,
        granted_by,
    ):
        now = datetime.now(UTC)
        status = "wait_effect" if start_time is not None and start_time > now else "active"
        params = {
            "tid": tenant_id,
            "oid": item.object_id,
            "status": status,
            "auth_source": auth_source,
            "auth_type": auth_type,
            "start_time": start_time,
            "expire_time": expire_time,
            "quota": json.dumps(quota or {}, ensure_ascii=False),
            "remark": remark,
            "granted_by": granted_by,
        }
        if item.object_type == OBJECT_TYPE_APP:
            return self._grant_app(params, now)
        return self._grant_resource(params)

    def revoke(self, tenant_id, object_type: str, object_id, remark: str = "") -> bool:
        params = {"tid": tenant_id, "oid": object_id, "remark": remark}
        if object_type == OBJECT_TYPE_APP:
            stmt = text(
                "UPDATE tenant_application_instance SET status = 'revoked', remark = :remark, "
                "updated_at = NOW() "
                "WHERE tenant_id = :tid AND application_id = :oid AND status <> 'revoked'"
            )
        else:
            stmt = text(
                "UPDATE tenant_resource_entitlement SET status = 'revoked', remark = :remark "
                "WHERE tenant_id = :tid AND resource_id = :oid AND status <> 'revoked'"
            )
        result = cast_cursor(self._session.execute(stmt, params))
        return result.rowcount == 1

    def purge(self, tenant_id, object_type: str, object_id) -> int:
        if object_type == OBJECT_TYPE_APP:
            stmt = text(
                "DELETE FROM tenant_application_instance "
                "WHERE tenant_id = :tid AND application_id = :oid"
            )
        else:
            stmt = text(
                "DELETE FROM tenant_resource_entitlement WHERE tenant_id = :tid AND resource_id = :oid"
            )
        result = cast_cursor(self._session.execute(stmt, {"tid": tenant_id, "oid": object_id}))
        return int(result.rowcount)

    # ========== 生命周期（P3-1：读侧已按时间计算，任务仅对齐持久状态） ==========
    def list_resource_wait_effective(self, now: datetime) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, resource_id FROM tenant_resource_entitlement "
                "WHERE status = 'wait_effect' AND start_time IS NOT NULL AND start_time <= :now"
            ),
            {"now": now},
        ).all()
        return [dict(row._mapping) for row in rows]

    def list_resource_expired(self, now: datetime) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, resource_id FROM tenant_resource_entitlement "
                "WHERE status = 'active' AND expire_time IS NOT NULL AND expire_time <= :now"
            ),
            {"now": now},
        ).all()
        return [dict(row._mapping) for row in rows]

    def revoke_grace_overdue(self, cutoff: datetime) -> int:
        """宽限期超期落库流转（P3-11）：双存储 expired 且 expire_time <= cutoff → revoked。"""
        total = 0
        for table in ("tenant_application_instance", "tenant_resource_entitlement"):
            result = cast_cursor(
                self._session.execute(
                    text(
                        f"UPDATE {table} SET status = 'revoked' "
                        "WHERE status = 'expired' AND expire_time IS NOT NULL "
                        "AND expire_time <= :cutoff"
                    ),
                    {"cutoff": cutoff},
                )
            )
            total += int(result.rowcount)
        return total

    def update_entitlement_status(self, entitlement_id, status: str) -> None:
        self._session.execute(
            text("UPDATE tenant_resource_entitlement SET status = :status WHERE id = :id"),
            {"id": entitlement_id, "status": status},
        )

    def purge_role_grants(self, tenant_id, object_type: str, object_id) -> int:
        """物理删除该权益支撑的角色授权行 resource_grants（purge 级联，P3-6）。"""
        result = cast_cursor(
            self._session.execute(
                text(
                    "DELETE FROM resource_grants "
                    "WHERE tenant_id = :tid AND resource_type = :otype AND resource_id = :oid"
                ),
                {"tid": tenant_id, "otype": object_type, "oid": object_id},
            )
        )
        return int(result.rowcount)

    def list_expiring(self, now: datetime, window_days: int) -> list[dict]:
        """双表中 window_days 天内到期的有效权益行（到期提醒扫描，P3-2）。"""
        horizon = now + timedelta(days=window_days)
        rows = self._session.execute(
            text(
                """
                SELECT 'app' AS object_type, i.application_id AS object_id, i.tenant_id,
                       a.name AS name, i.expire_time
                FROM tenant_application_instance i
                JOIN application a ON a.id = i.application_id
                WHERE i.status IN ('active', 'wait_effect')
                  AND i.expire_time IS NOT NULL AND i.expire_time > :now AND i.expire_time <= :horizon
                UNION ALL
                SELECT r.type, g.resource_id, g.tenant_id, r.name, g.expire_time
                FROM tenant_resource_entitlement g
                JOIN resource r ON r.id = g.resource_id
                WHERE g.status IN ('active', 'wait_effect')
                  AND g.expire_time IS NOT NULL AND g.expire_time > :now AND g.expire_time <= :horizon
                ORDER BY tenant_id, object_type, object_id
                """
            ),
            {"now": now, "horizon": horizon},
        ).all()
        return [dict(row._mapping) for row in rows]

    # ========== 内部 ==========
    def _grant_app(self, params: dict[str, Any], now: datetime):
        result = cast_cursor(
            self._session.execute(
                text(
                    """
                    UPDATE tenant_application_instance
                    SET status = :status, auth_source = :auth_source, auth_type = :auth_type,
                        start_time = :start_time, expire_time = :expire_time,
                        quota_json = CAST(:quota AS JSONB), remark = :remark,
                        granted_by = :granted_by, granted_at = NOW(), updated_at = NOW()
                    WHERE tenant_id = :tid AND application_id = :oid
                    """
                ),
                params,
            )
        )
        if result.rowcount == 1:
            row = self._session.execute(
                text(
                    "SELECT id FROM tenant_application_instance "
                    "WHERE tenant_id = :tid AND application_id = :oid"
                ),
                {"tid": params["tid"], "oid": params["oid"]},
            ).scalar_one()
            return row
        instance_id = new_uuid()
        self._session.execute(
            text(
                """
                INSERT INTO tenant_application_instance
                    (id, tenant_id, application_id, status, source, auth_source, auth_type,
                     contract_no, quota_json, start_time, expire_time, remark, granted_by, granted_at)
                VALUES
                    (:id, :tid, :oid, :status, :source, :auth_source, :auth_type,
                     '', CAST(:quota AS JSONB), :start_time, :expire_time, :remark, :granted_by, NOW())
                """
            ),
            {
                **params,
                "id": instance_id,
                "source": "granted" if params["auth_source"] == "OPS" else "marketplace",
            },
        )
        return instance_id

    def _grant_resource(self, params: dict[str, Any]):
        result = cast_cursor(
            self._session.execute(
                text(
                    """
                    UPDATE tenant_resource_entitlement
                    SET status = :status, auth_source = :auth_source, auth_type = :auth_type,
                        start_time = :start_time, expire_time = :expire_time,
                        quota_json = CAST(:quota AS JSONB), remark = :remark,
                        granted_by = :granted_by, granted_at = NOW()
                    WHERE tenant_id = :tid AND resource_id = :oid
                    """
                ),
                params,
            )
        )
        if result.rowcount == 1:
            row = self._session.execute(
                text(
                    "SELECT id FROM tenant_resource_entitlement WHERE tenant_id = :tid AND resource_id = :oid"
                ),
                {"tid": params["tid"], "oid": params["oid"]},
            ).scalar_one()
            return row
        grant_id = new_uuid()
        self._session.execute(
            text(
                """
                INSERT INTO tenant_resource_entitlement
                    (id, resource_id, tenant_id, granted_at, status, auth_source, auth_type,
                     start_time, expire_time, quota_json, remark, granted_by)
                VALUES
                    (:id, :oid, :tid, NOW(), :status, :auth_source, :auth_type,
                     :start_time, :expire_time, CAST(:quota AS JSONB), :remark, :granted_by)
                """
            ),
            {**params, "id": grant_id},
        )
        return grant_id

    @staticmethod
    def _filters(
        object_type: str | None, status: str | None, keyword: str | None
    ) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if object_type is not None:
            clauses.append("WHERE e.object_type = :otype")
            params["otype"] = object_type
        if status is not None:
            prefix = "AND" if clauses else "WHERE"
            clauses.append(f"{prefix} e.status = :status")
            params["status"] = status
        if keyword:
            prefix = "AND" if clauses else "WHERE"
            clauses.append(f"{prefix} e.name ILIKE :kw")
            params["kw"] = f"%{keyword}%"
        return (" " + " ".join(clauses) if clauses else ""), params

    def _to_view(self, row) -> EntitlementView:
        now = datetime.now(UTC)
        return EntitlementView(
            object_type=row.object_type,
            object_id=row.object_id,
            name=row.name,
            status=effective_status(
                row.status, row.start_time, row.expire_time, now, self._grace_days
            ),
            auth_source=row.auth_source,
            auth_type=row.auth_type,
            start_time=row.start_time,
            expire_time=row.expire_time,
            quota=dict(row.quota or {}),
            remark=row.remark or "",
            granted_at=row.granted_at,
            is_deprecated=bool(row.is_deprecated),
        )


def cast_cursor(result: Any) -> CursorResult:
    """raw SQL 结果按仓储约定收窄为 CursorResult 以读取 rowcount。"""
    from typing import cast

    return cast(CursorResult, result)
