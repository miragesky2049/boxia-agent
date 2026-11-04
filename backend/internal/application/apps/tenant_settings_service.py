"""租户运行时配置服务：默认模型 + 模型白名单 + 插件白名单。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from internal.application.errors import NotFoundError
from internal.domain.repository.apps_protocols import (
    ModelRepositoryProtocol,
    TenantSettingsRepositoryProtocol,
)


class TenantSettingsService:
    """提供给 admin 页面读写租户运行时配置。"""

    def __init__(
        self,
        settings_repo: TenantSettingsRepositoryProtocol,
        model_repo: ModelRepositoryProtocol,
        session: Session,
    ) -> None:
        """仓储由组合根构造注入；session 仅用于提交事务（session-per-service 风格）。"""
        self._session = session
        self._repo: TenantSettingsRepositoryProtocol = settings_repo
        self._model_repo: ModelRepositoryProtocol = model_repo

    def get(self, tenant_id: UUID) -> dict[str, Any]:
        """读租户配置；未配置时返回默认空结构。"""
        row = self._repo.get(tenant_id)
        return _row_to_view(row)

    def update(
        self,
        tenant_id: UUID,
        *,
        default_model_catalog_id: UUID | None,
        allowed_catalog_ids: list[UUID],
        plugin_whitelist: list[str],
    ) -> dict[str, Any]:
        """upsert 租户配置，字段合法性校验后落库。"""
        if default_model_catalog_id is not None:
            catalog = self._model_repo.get_catalog(default_model_catalog_id)
            if catalog is None:
                raise NotFoundError(f"模型目录不存在: {default_model_catalog_id}")

        for cid in allowed_catalog_ids:
            if self._model_repo.get_catalog(cid) is None:
                raise NotFoundError(f"模型目录不存在: {cid}")

        row = self._repo.upsert(
            tenant_id,
            default_model_catalog_id=default_model_catalog_id,
            allowed_catalog_ids=allowed_catalog_ids,
            plugin_whitelist=list(plugin_whitelist),
        )
        self._session.commit()
        return _row_to_view(row)

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._repo.list_all()
        return [_row_to_view(r) for r in rows]


def _row_to_view(row: dict | None) -> dict[str, Any]:
    if row is None:
        return {
            "default_model_catalog_id": None,
            "allowed_catalog_ids": [],
            "plugin_whitelist": [],
        }
    return {
        "default_model_catalog_id": row.get("default_model_catalog_id"),
        "allowed_catalog_ids": _as_str_list(row.get("allowed_catalog_ids")),
        "plugin_whitelist": _as_str_list(row.get("plugin_whitelist")),
        "updated_at": row.get("updated_at"),
    }


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return []
