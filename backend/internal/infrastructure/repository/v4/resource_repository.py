"""v4 统一资源仓储：resource + resource_grant。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class V4ResourceRepository:
    """统一资源仓储，用原生 SQL 操作。

    resource 表覆盖 tool / prompt / skill / knowledge 四类资源；
    resource_grant 表把平台资源开放给指定租户。
    """

    def __init__(self, session: Session):
        self._session = session

    # ========== resource CRUD ==========
    def create_resource(
        self,
        *,
        type: str,
        name: str,
        config: dict[str, Any],
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID:
        resource_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO resource (id, type, owner_type, owner_id, name, config) "
                "VALUES (:id, :type, :owner_type, :owner_id, :name, CAST(:config AS JSONB))"
            ),
            {
                "id": resource_id,
                "type": type,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "name": name,
                "config": json.dumps(config or {}),
            },
        )
        return resource_id

    def get_resource(self, resource_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, type, owner_type, owner_id, name, config, version, "
                "is_enabled, is_deprecated, created_at "
                "FROM resource WHERE id = :id"
            ),
            {"id": resource_id},
        ).first()
        return dict(row._mapping) if row else None

    def update_resource(
        self,
        resource_id: UUID,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
        is_deprecated: bool | None = None,
    ) -> None:
        sets: list[str] = []
        params: dict[str, Any] = {"id": resource_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if config is not None:
            sets.append("config = CAST(:config AS JSONB)")
            params["config"] = json.dumps(config)
        if is_enabled is not None:
            sets.append("is_enabled = :is_enabled")
            params["is_enabled"] = is_enabled
        if is_deprecated is not None:
            sets.append("is_deprecated = :is_deprecated")
            params["is_deprecated"] = is_deprecated
        if not sets:
            return
        self._session.execute(
            text(f"UPDATE resource SET {', '.join(sets)} WHERE id = :id"),
            params,
        )

    def delete_resource(self, resource_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM resource WHERE id = :id"),
            {"id": resource_id},
        )

    def list_resources(
        self,
        *,
        type: str | None = None,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        include_disabled: bool = False,
    ) -> list[dict]:
        sql = (
            "SELECT id, type, owner_type, owner_id, name, config, version, "
            "is_enabled, is_deprecated, created_at "
            "FROM resource WHERE 1=1"
        )
        params: dict[str, Any] = {}
        if type:
            sql += " AND type = :type"
            params["type"] = type
        if owner_type:
            sql += " AND owner_type = :owner_type"
            params["owner_type"] = owner_type
        if owner_id is not None:
            sql += " AND owner_id = :owner_id"
            params["owner_id"] = owner_id
        if not include_disabled:
            sql += " AND is_enabled = true AND is_deprecated = false"
        sql += " ORDER BY type, name"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    # ========== grant ==========
    def grant(self, resource_id: UUID, tenant_id: UUID) -> None:
        """把资源开放给租户。已 grant 则忽略（幂等）。"""
        self._session.execute(
            text(
                "INSERT INTO resource_grant (id, resource_id, tenant_id) "
                "VALUES (:id, :rid, :tid) "
                "ON CONFLICT (resource_id, tenant_id) DO NOTHING"
            ),
            {"id": new_uuid(), "rid": resource_id, "tid": tenant_id},
        )

    def revoke(self, resource_id: UUID, tenant_id: UUID) -> None:
        self._session.execute(
            text(
                "DELETE FROM resource_grant WHERE resource_id = :rid AND tenant_id = :tid"
            ),
            {"rid": resource_id, "tid": tenant_id},
        )

    def list_grants(self, resource_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, resource_id, tenant_id, granted_at "
                "FROM resource_grant WHERE resource_id = :rid ORDER BY granted_at"
            ),
            {"rid": resource_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def list_tenants_granted(self, resource_id: UUID) -> list[UUID]:
        rows = self._session.execute(
            text("SELECT tenant_id FROM resource_grant WHERE resource_id = :rid"),
            {"rid": resource_id},
        ).all()
        return [r[0] for r in rows]

    # ========== 运行时解析 ==========
    def resolve_for_tenant(self, resource_id: UUID, tenant_id: UUID) -> dict | None:
        """按租户解析资源：租户私有资源直接可见；平台资源必须已 grant。

        返回 None 表示资源不存在、已禁用、或租户无权访问。
        """
        row = self._session.execute(
            text(
                "SELECT r.id, r.type, r.owner_type, r.owner_id, r.name, r.config, r.version "
                "FROM resource r "
                "WHERE r.id = :rid AND r.is_enabled = true AND r.is_deprecated = false "
                "AND ( "
                "  (r.owner_type = 'tenant' AND r.owner_id = :tid) "
                "  OR (r.owner_type = 'platform' AND EXISTS ( "
                "    SELECT 1 FROM resource_grant g "
                "    WHERE g.resource_id = r.id AND g.tenant_id = :tid "
                "  )) "
                ")"
            ),
            {"rid": resource_id, "tid": tenant_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_available_for_tenant(
        self,
        tenant_id: UUID,
        *,
        type: str | None = None,
    ) -> list[dict]:
        """列出租户可用资源：平台已 grant 给该租户的 + 租户自建私有资源。"""
        sql = (
            "SELECT r.id, r.type, r.owner_type, r.owner_id, r.name, r.config, r.version "
            "FROM resource r "
            "WHERE r.is_enabled = true AND r.is_deprecated = false "
            "AND ( "
            "  (r.owner_type = 'tenant' AND r.owner_id = :tid) "
            "  OR (r.owner_type = 'platform' AND EXISTS ( "
            "    SELECT 1 FROM resource_grant g "
            "    WHERE g.resource_id = r.id AND g.tenant_id = :tid "
            "  )) "
            ")"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if type:
            sql += " AND r.type = :type"
            params["type"] = type
        sql += " ORDER BY r.type, r.name"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]
