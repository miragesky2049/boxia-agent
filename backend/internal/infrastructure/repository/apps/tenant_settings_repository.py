"""租户级运行时配置仓储：default model / 模型白名单 / 插件白名单。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class TenantSettingsRepository:
    """kv 风格的租户配置仓储，原生 SQL 操作。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, tenant_id, default_model_catalog_id, "
                "allowed_catalog_ids, plugin_whitelist, created_at, updated_at "
                "FROM tenant_settings WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).first()
        return dict(row._mapping) if row else None

    def upsert(
        self,
        tenant_id: UUID,
        *,
        default_model_catalog_id: UUID | None,
        allowed_catalog_ids: list[UUID],
        plugin_whitelist: list[str],
    ) -> dict:
        existing = self._session.execute(
            text("SELECT id FROM tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).first()
        allowed_json = json.dumps([str(x) for x in allowed_catalog_ids])
        whitelist_json = json.dumps(list(plugin_whitelist))
        if existing:
            self._session.execute(
                text(
                    "UPDATE tenant_settings SET "
                    "default_model_catalog_id = :mid, "
                    "allowed_catalog_ids = CAST(:allowed AS JSONB), "
                    "plugin_whitelist = CAST(:whitelist AS JSONB), "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid"
                ),
                {
                    "tid": tenant_id,
                    "mid": default_model_catalog_id,
                    "allowed": allowed_json,
                    "whitelist": whitelist_json,
                },
            )
        else:
            self._session.execute(
                text(
                    "INSERT INTO tenant_settings "
                    "(id, tenant_id, default_model_catalog_id, allowed_catalog_ids, plugin_whitelist) "
                    "VALUES (:id, :tid, :mid, CAST(:allowed AS JSONB), CAST(:whitelist AS JSONB))"
                ),
                {
                    "id": new_uuid(),
                    "tid": tenant_id,
                    "mid": default_model_catalog_id,
                    "allowed": allowed_json,
                    "whitelist": whitelist_json,
                },
            )
        return self.get(tenant_id)  # type: ignore[return-value]

    def list_all(self) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, default_model_catalog_id, "
                "allowed_catalog_ids, plugin_whitelist, created_at, updated_at "
                "FROM tenant_settings ORDER BY updated_at DESC"
            )
        ).all()
        return [dict(r._mapping) for r in rows]
