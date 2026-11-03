"""套餐模板仓储实现：entitlement_plan 主表 + entitlement_plan_item 条目聚合。

与权益仓储同为 SQLAlchemy Core / text 裸 SQL 风格（infra → domain），
条目经外键级联随模板删除；模板不落权益，开通由服务层展开为批量条目。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.entitlement_plan import EntitlementPlan
from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.repository.apps.entitlement_repository import cast_cursor


class EntitlementPlanRepository:
    """结构性满足 EntitlementPlanRepositoryProtocol 的 PostgreSQL 实现。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, plan_id: UUID) -> EntitlementPlan | None:
        row = self._session.execute(
            text(
                "SELECT id, code, name, description, auth_type, duration_days, "
                "quota_json, is_active FROM entitlement_plan WHERE id = :pid"
            ),
            {"pid": plan_id},
        ).first()
        if row is None:
            return None
        return self._to_plan(row, self._items([plan_id]).get(plan_id, ()))

    def get_by_code(self, code: str) -> EntitlementPlan | None:
        row = self._session.execute(
            text(
                "SELECT id, code, name, description, auth_type, duration_days, "
                "quota_json, is_active FROM entitlement_plan WHERE code = :code"
            ),
            {"code": code},
        ).first()
        if row is None:
            return None
        return self._to_plan(row, self._items([row.id]).get(row.id, ()))

    def list_page(
        self, keyword: str | None, page: int, page_size: int
    ) -> tuple[list[EntitlementPlan], int]:
        params: dict[str, Any] = {}
        where = ""
        if keyword:
            where = "WHERE code ILIKE :kw OR name ILIKE :kw"
            params["kw"] = f"%{keyword}%"
        total = self._session.execute(
            text(f"SELECT count(*) FROM entitlement_plan {where}"), params
        ).scalar_one()
        params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
        rows = self._session.execute(
            text(
                "SELECT id, code, name, description, auth_type, duration_days, quota_json, is_active "
                f"FROM entitlement_plan {where} ORDER BY created_at DESC, code LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        items_map = self._items([row.id for row in rows])
        return [self._to_plan(row, items_map.get(row.id, ())) for row in rows], int(total)

    def create(
        self,
        *,
        code: str,
        name: str,
        description: str,
        auth_type: str,
        duration_days: int | None,
        quota: dict[str, Any],
        items: tuple[EntitlementItem, ...],
    ) -> UUID:
        plan_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO entitlement_plan "
                "(id, code, name, description, auth_type, duration_days, quota_json, is_active) "
                "VALUES (:id, :code, :name, :description, :auth_type, :duration_days, "
                "CAST(:quota AS JSONB), TRUE)"
            ),
            {
                "id": plan_id,
                "code": code,
                "name": name,
                "description": description,
                "auth_type": auth_type,
                "duration_days": duration_days,
                "quota": json.dumps(quota or {}, ensure_ascii=False),
            },
        )
        for item in items:
            self._session.execute(
                text(
                    "INSERT INTO entitlement_plan_item (id, plan_id, object_type, object_id) "
                    "VALUES (:id, :pid, :otype, :oid)"
                ),
                {
                    "id": new_uuid(),
                    "pid": plan_id,
                    "otype": item.object_type,
                    "oid": item.object_id,
                },
            )
        return plan_id

    def delete(self, plan_id: UUID) -> bool:
        result = cast_cursor(
            self._session.execute(
                text("DELETE FROM entitlement_plan WHERE id = :pid"), {"pid": plan_id}
            )
        )
        return result.rowcount == 1

    # ========== 内部 ==========
    def _items(self, plan_ids: list[UUID]) -> dict[UUID, tuple[EntitlementItem, ...]]:
        if not plan_ids:
            return {}
        rows = self._session.execute(
            text(
                "SELECT plan_id, object_type, object_id FROM entitlement_plan_item "
                "WHERE plan_id = ANY(:pids) ORDER BY object_type, object_id"
            ),
            {"pids": plan_ids},
        ).all()
        grouped: dict[UUID, list[EntitlementItem]] = {}
        for row in rows:
            grouped.setdefault(row.plan_id, []).append(
                EntitlementItem(row.object_type, row.object_id)
            )
        return {pid: tuple(items) for pid, items in grouped.items()}

    @staticmethod
    def _to_plan(row: Any, items: tuple[EntitlementItem, ...]) -> EntitlementPlan:
        return EntitlementPlan(
            id=row.id,
            code=row.code,
            name=row.name,
            description=row.description,
            auth_type=row.auth_type,
            duration_days=row.duration_days,
            quota=dict(row.quota_json or {}),
            is_active=bool(row.is_active),
            items=items,
        )
