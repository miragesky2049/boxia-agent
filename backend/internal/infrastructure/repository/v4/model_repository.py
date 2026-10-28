"""v4 模型目录仓储：model_provider + model_catalog。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class V4ModelRepository:
    """v4 模型目录仓储，用原生 SQL 操作。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== provider ==========
    def upsert_provider(
        self,
        name: str,
        base_url: str,
        api_key: str,
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID:
        existing = self._session.execute(
            text("SELECT id FROM model_provider WHERE name = :name"),
            {"name": name},
        ).first()
        if existing:
            provider_id = existing[0]
            self._session.execute(
                text(
                    "UPDATE model_provider SET base_url = :base_url, api_key = :api_key "
                    "WHERE id = :id"
                ),
                {"base_url": base_url, "api_key": api_key, "id": provider_id},
            )
            return provider_id
        provider_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO model_provider (id, name, base_url, api_key, owner_type, owner_id) "
                "VALUES (:id, :name, :base_url, :api_key, :owner_type, :owner_id)"
            ),
            {
                "id": provider_id,
                "name": name,
                "base_url": base_url,
                "api_key": api_key,
                "owner_type": owner_type,
                "owner_id": owner_id,
            },
        )
        return provider_id

    def create_provider(
        self,
        name: str,
        base_url: str,
        api_key: str,
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID:
        provider_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO model_provider (id, name, base_url, api_key, owner_type, owner_id) "
                "VALUES (:id, :name, :base_url, :api_key, :owner_type, :owner_id)"
            ),
            {
                "id": provider_id,
                "name": name,
                "base_url": base_url,
                "api_key": api_key,
                "owner_type": owner_type,
                "owner_id": owner_id,
            },
        )
        return provider_id

    def update_provider(
        self,
        provider_id: UUID,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        is_enabled: bool | None = None,
    ) -> None:
        sets: list[str] = []
        params: dict[str, Any] = {"id": provider_id}
        if base_url is not None:
            sets.append("base_url = :base_url")
            params["base_url"] = base_url
        if api_key is not None:
            sets.append("api_key = :api_key")
            params["api_key"] = api_key
        if is_enabled is not None:
            sets.append("is_enabled = :is_enabled")
            params["is_enabled"] = is_enabled
        if not sets:
            return
        self._session.execute(
            text(f"UPDATE model_provider SET {', '.join(sets)} WHERE id = :id"),
            params,
        )

    def delete_provider(self, provider_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM model_provider WHERE id = :id"),
            {"id": provider_id},
        )

    def get_provider(self, provider_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, name, base_url, api_key, owner_type, owner_id, is_enabled, created_at "
                "FROM model_provider WHERE id = :id"
            ),
            {"id": provider_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_providers(self, owner_type: str | None = None) -> list[dict]:
        sql = (
            "SELECT id, name, base_url, owner_type, owner_id, is_enabled, created_at "
            "FROM model_provider"
        )
        params: dict[str, Any] = {}
        if owner_type:
            sql += " WHERE owner_type = :owner_type"
            params["owner_type"] = owner_type
        sql += " ORDER BY name"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    # ========== catalog ==========
    def upsert_catalog(
        self,
        provider_id: UUID,
        model_id: str,
        display_name: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> UUID:
        capabilities_json = json.dumps(capabilities or {})
        existing = self._session.execute(
            text("SELECT id FROM model_catalog WHERE model_id = :mid"),
            {"mid": model_id},
        ).first()
        if existing:
            catalog_id = existing[0]
            self._session.execute(
                text(
                    "UPDATE model_catalog SET provider_id = :pid, display_name = :dn, "
                    "capabilities = CAST(:cap AS JSONB) WHERE id = :id"
                ),
                {
                    "pid": provider_id,
                    "dn": display_name,
                    "cap": capabilities_json,
                    "id": catalog_id,
                },
            )
            return catalog_id
        catalog_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO model_catalog (id, provider_id, model_id, display_name, capabilities) "
                "VALUES (:id, :pid, :mid, :dn, CAST(:cap AS JSONB))"
            ),
            {
                "id": catalog_id,
                "pid": provider_id,
                "mid": model_id,
                "dn": display_name,
                "cap": capabilities_json,
            },
        )
        return catalog_id

    def create_catalog(
        self,
        provider_id: UUID,
        model_id: str,
        display_name: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> UUID:
        catalog_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO model_catalog (id, provider_id, model_id, display_name, capabilities) "
                "VALUES (:id, :pid, :mid, :dn, CAST(:cap AS JSONB))"
            ),
            {
                "id": catalog_id,
                "pid": provider_id,
                "mid": model_id,
                "dn": display_name,
                "cap": json.dumps(capabilities or {}),
            },
        )
        return catalog_id

    def update_catalog(
        self,
        catalog_id: UUID,
        *,
        provider_id: UUID | None = None,
        display_name: str | None = None,
        capabilities: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
    ) -> None:
        sets: list[str] = []
        params: dict[str, Any] = {"id": catalog_id}
        if provider_id is not None:
            sets.append("provider_id = :pid")
            params["pid"] = provider_id
        if display_name is not None:
            sets.append("display_name = :dn")
            params["dn"] = display_name
        if capabilities is not None:
            sets.append("capabilities = CAST(:cap AS JSONB)")
            params["cap"] = json.dumps(capabilities)
        if is_enabled is not None:
            sets.append("is_enabled = :is_enabled")
            params["is_enabled"] = is_enabled
        if not sets:
            return
        self._session.execute(
            text(f"UPDATE model_catalog SET {', '.join(sets)} WHERE id = :id"),
            params,
        )

    def delete_catalog(self, catalog_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM model_catalog WHERE id = :id"),
            {"id": catalog_id},
        )

    def get_catalog(self, catalog_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, provider_id, model_id, display_name, capabilities, is_enabled, created_at "
                "FROM model_catalog WHERE id = :id"
            ),
            {"id": catalog_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_catalog_full(self) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT c.id, c.model_id, c.display_name, c.capabilities, c.is_enabled, "
                "c.provider_id, p.name AS provider_name, p.base_url "
                "FROM model_catalog c "
                "JOIN model_provider p ON p.id = c.provider_id "
                "ORDER BY p.name, c.model_id"
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    def resolve_model(self, model_id: str) -> dict | None:
        """根据 model_id 解析出 provider 连接信息 + 模型元数据。"""
        row = self._session.execute(
            text(
                "SELECT c.model_id, c.display_name, c.capabilities, "
                "p.name AS provider_name, p.base_url, p.api_key "
                "FROM model_catalog c "
                "JOIN model_provider p ON p.id = c.provider_id "
                "WHERE c.model_id = :mid AND c.is_enabled = true AND p.is_enabled = true"
            ),
            {"mid": model_id},
        ).first()
        return dict(row._mapping) if row else None

    def resolve_model_for_tenant(self, model_id: str, tenant_id: UUID) -> dict | None:
        """按租户解析模型：优先租户自带 provider，回退平台 provider。

        阶段二：租户可自带 API key（owner_type=tenant, owner_id=tenant_id）。
        当前阶段一：所有 provider 都是 platform，此方法等价于 resolve_model。
        """
        row = self._session.execute(
            text(
                "SELECT c.model_id, c.display_name, c.capabilities, "
                "p.name AS provider_name, p.base_url, p.api_key, p.owner_type "
                "FROM model_catalog c "
                "JOIN model_provider p ON p.id = c.provider_id "
                "WHERE c.model_id = :mid AND c.is_enabled = true AND p.is_enabled = true "
                "AND (p.owner_type = 'platform' OR (p.owner_type = 'tenant' AND p.owner_id = :tid)) "
                "ORDER BY CASE p.owner_type WHEN 'tenant' THEN 0 ELSE 1 END "
                "LIMIT 1"
            ),
            {"mid": model_id, "tid": tenant_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_catalog(self) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT c.model_id, c.display_name, c.capabilities, p.name AS provider_name "
                "FROM model_catalog c "
                "JOIN model_provider p ON p.id = c.provider_id "
                "WHERE c.is_enabled = true AND p.is_enabled = true "
                "ORDER BY p.name, c.model_id"
            )
        ).all()
        return [dict(r._mapping) for r in rows]
