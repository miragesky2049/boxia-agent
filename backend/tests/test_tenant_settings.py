"""T16：租户运行时配置（默认模型 + 模型白名单 + 插件白名单）单测。

验证：
1. 未配置租户时 get 返回空结构
2. upsert 后字段可读出
3. default_model_catalog_id / allowed_catalog_ids 合法性校验：不存在的 catalog 抛 NotFoundError
4. plugin_whitelist 覆盖式写入
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.application.apps.tenant_settings_service import TenantSettingsService
from internal.application.errors import NotFoundError


class FakeSettingsRepo:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def get(self, tenant_id):
        return self.store.get(str(tenant_id))

    def upsert(self, tenant_id, *, default_model_catalog_id, allowed_catalog_ids, plugin_whitelist):
        self.store[str(tenant_id)] = {
            "id": uuid4(),
            "tenant_id": str(tenant_id),
            "default_model_catalog_id": str(default_model_catalog_id) if default_model_catalog_id else None,
            "allowed_catalog_ids": [str(x) for x in allowed_catalog_ids],
            "plugin_whitelist": list(plugin_whitelist),
            "updated_at": "2026-10-31",
        }
        return self.store[str(tenant_id)]

    def list_all(self):
        return list(self.store.values())


class FakeModelRepo:
    def __init__(self, catalogs: set[str]) -> None:
        self._catalogs = catalogs

    def get_catalog(self, catalog_id):
        cid = str(catalog_id)
        if cid not in self._catalogs:
            return None
        return {"id": cid, "model_id": f"model-{cid[:8]}"}


def _make_service(catalogs: set[str] | None = None) -> tuple[TenantSettingsService, FakeSettingsRepo]:
    session = MagicMock()
    service = TenantSettingsService(session)
    repo = FakeSettingsRepo()
    service._repo = repo  # type: ignore[assignment]
    service._model_repo = FakeModelRepo(catalogs or set())  # type: ignore[assignment]
    return service, repo


def test_get_returns_empty_when_no_row():
    service, _ = _make_service()
    view = service.get(uuid4())
    assert view == {
        "default_model_catalog_id": None,
        "allowed_catalog_ids": [],
        "plugin_whitelist": [],
    }


def test_upsert_persists_fields():
    default_cid = uuid4()
    allowed = [uuid4(), uuid4()]
    service, repo = _make_service(
        catalogs={str(default_cid), str(allowed[0]), str(allowed[1])}
    )
    tenant_id = uuid4()
    view = service.update(
        tenant_id,
        default_model_catalog_id=default_cid,
        allowed_catalog_ids=allowed,
        plugin_whitelist=["get_weather", "web_search"],
    )
    assert view["default_model_catalog_id"] == str(default_cid)
    assert view["allowed_catalog_ids"] == [str(x) for x in allowed]
    assert view["plugin_whitelist"] == ["get_weather", "web_search"]
    assert str(tenant_id) in repo.store


def test_upsert_rejects_unknown_default_catalog():
    service, _ = _make_service(catalogs=set())
    with pytest.raises(NotFoundError):
        service.update(
            uuid4(),
            default_model_catalog_id=uuid4(),
            allowed_catalog_ids=[],
            plugin_whitelist=[],
        )


def test_upsert_rejects_unknown_allowed_catalog():
    known = str(uuid4())
    service, _ = _make_service(catalogs={known})
    with pytest.raises(NotFoundError):
        service.update(
            uuid4(),
            default_model_catalog_id=None,
            allowed_catalog_ids=[uuid4()],  # 不在已知集合
            plugin_whitelist=[],
        )


def test_upsert_overwrites_previous_whitelist():
    service, repo = _make_service()
    tenant_id = uuid4()
    service.update(
        tenant_id,
        default_model_catalog_id=None,
        allowed_catalog_ids=[],
        plugin_whitelist=["a", "b"],
    )
    service.update(
        tenant_id,
        default_model_catalog_id=None,
        allowed_catalog_ids=[],
        plugin_whitelist=["c"],
    )
    view = service.get(tenant_id)
    assert view["plugin_whitelist"] == ["c"]
    assert len(repo.store) == 1  # upsert 覆盖，不新增行
