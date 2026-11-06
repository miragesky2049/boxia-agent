"""app_admin_scope 仓储（0069 二期）：应用 ↔ 管理单元关联。

与 application_repository 同为 session-per-service 裸 SQL 风格；
mgmt_unit_id 对 mgmt_units CASCADE，读取时 JOIN 过滤历史孤儿，口径与 0068 白名单一致。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class AdminScopeRepository:
    """结构性满足 AdminScopeRepositoryProtocol（web/deps 组合根注入）。"""

    def __init__(self, session: Session):
        self._session = session

    def list_scopes(self, application_id: UUID, tenant_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                """
                SELECT s.mgmt_unit_id AS mgmt_unit_id, u.name AS mgmt_unit_name,
                       u.code AS mgmt_unit_code
                FROM app_admin_scope s
                JOIN mgmt_units u ON u.id = s.mgmt_unit_id
                WHERE s.application_id = :aid AND s.tenant_id = :tid
                ORDER BY u.name
                """
            ),
            {"aid": application_id, "tid": tenant_id},
        ).fetchall()
        return [
            {
                "mgmt_unit_id": str(row.mgmt_unit_id),
                "mgmt_unit_name": row.mgmt_unit_name,
                "mgmt_unit_code": row.mgmt_unit_code,
            }
            for row in rows
        ]

    def list_unit_ids(self, application_id: UUID, tenant_id: UUID) -> list[UUID]:
        rows = self._session.execute(
            text(
                """
                SELECT s.mgmt_unit_id
                FROM app_admin_scope s
                JOIN mgmt_units u ON u.id = s.mgmt_unit_id
                WHERE s.application_id = :aid AND s.tenant_id = :tid
                """
            ),
            {"aid": application_id, "tid": tenant_id},
        ).fetchall()
        return [row.mgmt_unit_id for row in rows]

    def unit_exists(self, tenant_id: UUID, mgmt_unit_id: UUID) -> bool:
        """校验管理单元存在且属于本租户（跨租户关联防御）。"""
        row = self._session.execute(
            text(
                "SELECT 1 FROM mgmt_units WHERE id = :uid AND tenant_id = :tid LIMIT 1"
            ),
            {"uid": mgmt_unit_id, "tid": tenant_id},
        ).first()
        return row is not None

    def add_scope(self, application_id: UUID, tenant_id: UUID, mgmt_unit_id: UUID) -> None:
        self._session.execute(
            text(
                """
                INSERT INTO app_admin_scope (id, application_id, tenant_id, mgmt_unit_id)
                VALUES (:id, :aid, :tid, :uid)
                ON CONFLICT (application_id, mgmt_unit_id) DO NOTHING
                """
            ),
            {"id": new_uuid(), "aid": application_id, "tid": tenant_id, "uid": mgmt_unit_id},
        )
        self._session.flush()

    def remove_scope(self, application_id: UUID, tenant_id: UUID, mgmt_unit_id: UUID) -> None:
        self._session.execute(
            text(
                """
                DELETE FROM app_admin_scope
                WHERE application_id = :aid AND tenant_id = :tid AND mgmt_unit_id = :uid
                """
            ),
            {"aid": application_id, "tid": tenant_id, "uid": mgmt_unit_id},
        )
        self._session.flush()

    def list_unit_ids_by_app(self, tenant_id: UUID) -> dict[UUID, set[UUID]]:
        rows = self._session.execute(
            text(
                """
                SELECT s.application_id, s.mgmt_unit_id
                FROM app_admin_scope s
                JOIN mgmt_units u ON u.id = s.mgmt_unit_id
                WHERE s.tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        ).fetchall()
        grouped: dict[UUID, set[UUID]] = {}
        for row in rows:
            grouped.setdefault(row.application_id, set()).add(row.mgmt_unit_id)
        return grouped
