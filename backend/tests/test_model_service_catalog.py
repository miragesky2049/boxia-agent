"""T8: ModelService.list_catalog 返回字段与默认值兜底单测。

验证：
- DB 表为空时回退到 settings.llm_model_id + llm_temperature/llm_max_tokens
- DB 有记录时 capabilities 自动补 default_temperature / default_max_tokens
- 已有 capabilities 自定义值不被覆盖
"""

from __future__ import annotations

from unittest.mock import MagicMock

from internal.application.apps.model_service import ModelService


def _make_service(repo_rows: list[dict]) -> ModelService:
    repo = MagicMock()
    repo.list_catalog.return_value = repo_rows
    service = ModelService.__new__(ModelService)
    service._repo = repo
    return service


def test_list_catalog_falls_back_to_settings_when_empty() -> None:
    service = _make_service([])
    rows = service.list_catalog()
    assert len(rows) == 1
    row = rows[0]
    assert row["provider_name"] == "settings"
    assert "model_id" in row
    assert "default_temperature" in row["capabilities"]
    assert "default_max_tokens" in row["capabilities"]


def test_list_catalog_normalizes_capabilities_with_defaults() -> None:
    db_rows = [
        {
            "model_id": "gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "provider_name": "openai",
            "capabilities": {"supports_tools": True},
        },
    ]
    service = _make_service(db_rows)
    rows = service.list_catalog()
    assert len(rows) == 1
    row = rows[0]
    assert row["model_id"] == "gpt-4o-mini"
    assert row["display_name"] == "GPT-4o mini"
    assert row["provider_name"] == "openai"
    assert row["capabilities"]["supports_tools"] is True
    assert "default_temperature" in row["capabilities"]
    assert "default_max_tokens" in row["capabilities"]


def test_list_catalog_does_not_override_existing_capabilities() -> None:
    db_rows = [
        {
            "model_id": "custom-model",
            "display_name": "Custom",
            "provider_name": "internal",
            "capabilities": {
                "default_temperature": 0.2,
                "default_max_tokens": 2048,
            },
        },
    ]
    service = _make_service(db_rows)
    rows = service.list_catalog()
    assert rows[0]["capabilities"]["default_temperature"] == 0.2
    assert rows[0]["capabilities"]["default_max_tokens"] == 2048
