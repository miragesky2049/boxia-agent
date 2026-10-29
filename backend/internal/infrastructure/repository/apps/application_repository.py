"""应用仓储：application + application_graph + tenant_instance。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class ApplicationRepository:
    """应用仓储，用原生 SQL 操作新表。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== application CRUD ==========
    def create_application(
        self,
        name: str,
        owner_type: str,
        owner_id: UUID | None,
        description: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        app_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application (id, owner_type, owner_id, name, description, created_by) "
                "VALUES (:id, :owner_type, :owner_id, :name, :description, :created_by)"
            ),
            {
                "id": app_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "name": name,
                "description": description,
                "created_by": created_by,
            },
        )
        return app_id

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = NOW()"]
        params: dict[str, Any] = {"id": application_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if description is not None:
            sets.append("description = :description")
            params["description"] = description
        if avatar_url is not None:
            sets.append("avatar_url = :avatar_url")
            params["avatar_url"] = avatar_url
        self._session.execute(
            text(f"UPDATE application SET {', '.join(sets)} WHERE id = :id"),
            params,
        )

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None:
        self._session.execute(
            text(
                "UPDATE application SET is_listed_in_market = :listed, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"listed": listed, "id": application_id},
        )

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        self._session.execute(
            text(
                "UPDATE application SET is_enabled = :enabled, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"enabled": enabled, "id": application_id},
        )

    def get_application(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, owner_type, owner_id, name, avatar_url, description, is_enabled, "
                "is_listed_in_market, visibility_mode, created_by, created_at, updated_at "
                "FROM application WHERE id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_applications(
        self,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        sql = (
            "SELECT id, owner_type, owner_id, name, avatar_url, description, is_enabled, "
            "is_listed_in_market, created_at, updated_at FROM application"
        )
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if owner_type:
            conditions.append("owner_type = :owner_type")
            params["owner_type"] = owner_type
        if owner_id is not None:
            conditions.append("owner_id = :owner_id")
            params["owner_id"] = owner_id
        if include_marketplace_only:
            conditions.append("is_listed_in_market = true")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    def list_marketplace(self) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, name, avatar_url, description FROM application "
                "WHERE owner_type = 'platform' AND is_enabled = true "
                "AND is_listed_in_market = true"
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    # ========== graph ==========
    def create_graph(self, application_id: UUID, graph: dict) -> None:
        self._session.execute(
            text(
                "INSERT INTO application_graph (application_id, graph) "
                "VALUES (:aid, CAST(:graph AS JSONB))"
            ),
            {"aid": application_id, "graph": json.dumps(graph)},
        )

    def update_graph(self, application_id: UUID, graph: dict, runtime_mode: str = "dag") -> None:
        """覆盖写入 graph；不存在则插入。"""
        existing = self._session.execute(
            text("SELECT 1 FROM application_graph WHERE application_id = :aid"),
            {"aid": application_id},
        ).first()
        if existing:
            self._session.execute(
                text(
                    "UPDATE application_graph SET graph = CAST(:graph AS JSONB), "
                    "runtime_mode = :mode, updated_at = NOW() WHERE application_id = :aid"
                ),
                {"aid": application_id, "graph": json.dumps(graph), "mode": runtime_mode},
            )
        else:
            self._session.execute(
                text(
                    "INSERT INTO application_graph (application_id, graph, runtime_mode) "
                    "VALUES (:aid, CAST(:graph AS JSONB), :mode)"
                ),
                {"aid": application_id, "graph": json.dumps(graph), "mode": runtime_mode},
            )

    def get_graph(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT graph, runtime_mode, graph_schema_version "
                "FROM application_graph WHERE application_id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    # ========== tenant instance ==========
    def subscribe(self, tenant_id: UUID, application_id: UUID) -> UUID:
        instance_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source) "
                "VALUES (:id, :tid, :aid, 'active', 'marketplace')"
            ),
            {"id": instance_id, "tid": tenant_id, "aid": application_id},
        )
        return instance_id

    def get_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT * FROM tenant_application_instance "
                "WHERE tenant_id = :tid AND application_id = :aid"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_instances(self, tenant_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT i.*, a.name, a.description, a.avatar_url "
                "FROM tenant_application_instance i "
                "JOIN application a ON a.id = i.application_id "
                "WHERE i.tenant_id = :tid AND i.status = 'active'"
            ),
            {"tid": tenant_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    # ========== field version ==========
    def get_latest_field_versions(self, application_id: UUID) -> dict[str, dict]:
        """返回 {field_path: {version, value, changelog, created_at}}，每字段取最新版本。"""
        rows = self._session.execute(
            text(
                "SELECT DISTINCT ON (field_path) field_path, version, value, changelog, created_at "
                "FROM application_field_version "
                "WHERE application_id = :aid "
                "ORDER BY field_path, version DESC"
            ),
            {"aid": application_id},
        ).all()
        return {
            r._mapping["field_path"]: {
                "version": r._mapping["version"],
                "value": r._mapping["value"],
                "changelog": r._mapping["changelog"],
                "created_at": r._mapping["created_at"],
            }
            for r in rows
        }

    def insert_field_version(
        self,
        application_id: UUID,
        field_path: str,
        version: int,
        value: Any,
        changelog: str = "",
    ) -> UUID:
        vid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application_field_version "
                "(id, application_id, field_path, version, value, changelog, published_at) "
                "VALUES (:id, :aid, :path, :ver, CAST(:val AS JSONB), :log, NOW())"
            ),
            {
                "id": vid,
                "aid": application_id,
                "path": field_path,
                "ver": version,
                "val": json.dumps(value),
                "log": changelog,
            },
        )
        return vid

    def list_field_versions(
        self,
        application_id: UUID,
        field_path: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT field_path, version, value, changelog, published_at, created_at "
            "FROM application_field_version WHERE application_id = :aid"
        )
        params: dict[str, Any] = {"aid": application_id}
        if field_path:
            sql += " AND field_path = :path"
            params["path"] = field_path
        sql += " ORDER BY field_path, version DESC"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    def get_field_version(
        self,
        application_id: UUID,
        field_path: str,
        version: int,
    ) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT field_path, version, value, changelog, published_at, created_at "
                "FROM application_field_version "
                "WHERE application_id = :aid AND field_path = :path AND version = :ver"
            ),
            {"aid": application_id, "path": field_path, "ver": version},
        ).first()
        return dict(row._mapping) if row else None

    # ========== tenant field pin ==========
    def list_pins(self, tenant_id: UUID, application_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT field_path, pinned_version, created_at "
                "FROM tenant_field_pin "
                "WHERE tenant_id = :tid AND application_id = :aid"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def upsert_pin(
        self,
        tenant_id: UUID,
        application_id: UUID,
        field_path: str,
        version: int,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO tenant_field_pin (id, tenant_id, application_id, field_path, pinned_version) "
                "VALUES (:id, :tid, :aid, :path, :ver) "
                "ON CONFLICT ON CONSTRAINT ux_field_pin_unique "
                "DO UPDATE SET pinned_version = EXCLUDED.pinned_version, created_at = NOW()"
            ),
            {
                "id": new_uuid(),
                "tid": tenant_id,
                "aid": application_id,
                "path": field_path,
                "ver": version,
            },
        )

    def delete_pin(
        self,
        tenant_id: UUID,
        application_id: UUID,
        field_path: str,
    ) -> bool:
        deleted = self._session.execute(
            text(
                "DELETE FROM tenant_field_pin "
                "WHERE tenant_id = :tid AND application_id = :aid AND field_path = :path"
            ),
            {"tid": tenant_id, "aid": application_id, "path": field_path},
        )
        return int(getattr(deleted, "rowcount", 0) or 0) > 0
