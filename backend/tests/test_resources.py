"""技能 / 工具 / 组件 / 提示词四个资源的 CRUD 测试。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

RESOURCE_CASES: list[tuple[str, str, dict[str, Any]]] = [
    (
        "skills",
        "技能",
        {"content": "按要求生成陪练剧本", "config": {"engine": "script"}},
    ),
    (
        "tools",
        "工具",
        {"type": "http", "config": {"url": "https://example.com/api", "method": "GET"}},
    ),
    (
        "components",
        "组件",
        {"type": "card", "config": {"layout": "grid"}},
    ),
    (
        "prompts",
        "提示词",
        {"content": "你好，{{name}}", "variables": ["name"], "category": "system"},
    ),
]

CASE_IDS = [case[0] for case in RESOURCE_CASES]


def _payload(case: tuple[str, str, dict[str, Any]], name: str = "示例资源") -> dict[str, Any]:
    return {"name": name, "description": "描述", "is_enabled": True, **case[2]}


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_requires_authentication(client: TestClient, case) -> None:
    endpoint = case[0]

    assert client.get(f"/api/v1/admin/{endpoint}").status_code == 401
    assert client.post(f"/api/v1/admin/{endpoint}", json=_payload(case)).status_code == 401


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_create_and_get(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]

    created = client.post(f"/api/v1/admin/{endpoint}", json=_payload(case), headers=auth_headers)
    assert created.status_code == 201, created.text

    body = created.json()
    assert body["id"] > 0
    assert body["name"] == "示例资源"
    assert body["description"] == "描述"
    assert body["is_enabled"] is True
    assert body["created_at"] and body["updated_at"]
    for key, value in case[2].items():
        assert body[key] == value

    detail = client.get(f"/api/v1/admin/{endpoint}/{body['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == body["id"]


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_duplicate_name_conflict(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    client.post(f"/api/v1/admin/{endpoint}", json=_payload(case, "Alpha"), headers=auth_headers)

    response = client.post(
        f"/api/v1/admin/{endpoint}", json=_payload(case, "alpha"), headers=auth_headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_update(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    created = client.post(
        f"/api/v1/admin/{endpoint}", json=_payload(case, "旧名称"), headers=auth_headers
    ).json()

    updated = client.put(
        f"/api/v1/admin/{endpoint}/{created['id']}",
        json=_payload(case, "新名称") | {"description": "新描述", "is_enabled": False},
        headers=auth_headers,
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "新名称"
    assert body["description"] == "新描述"
    assert body["is_enabled"] is False
    assert body["updated_at"] >= created["updated_at"]


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_update_duplicate_name(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    first = client.post(
        f"/api/v1/admin/{endpoint}", json=_payload(case, "First"), headers=auth_headers
    ).json()
    client.post(f"/api/v1/admin/{endpoint}", json=_payload(case, "Second"), headers=auth_headers)

    response = client.put(
        f"/api/v1/admin/{endpoint}/{first['id']}",
        json=_payload(case, "SECOND"),
        headers=auth_headers,
    )

    assert response.status_code == 409


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_update_self_name_allowed(client: TestClient, auth_headers, case) -> None:
    """更新时保留自身名称不应被判为重名。"""
    endpoint = case[0]
    created = client.post(
        f"/api/v1/admin/{endpoint}", json=_payload(case, "Keep Me"), headers=auth_headers
    ).json()

    response = client.put(
        f"/api/v1/admin/{endpoint}/{created['id']}",
        json=_payload(case, "Keep Me") | {"description": "仅改描述"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["description"] == "仅改描述"


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_delete(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    created = client.post(
        f"/api/v1/admin/{endpoint}", json=_payload(case), headers=auth_headers
    ).json()

    assert (
        client.delete(f"/api/v1/admin/{endpoint}/{created['id']}", headers=auth_headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/admin/{endpoint}/{created['id']}", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/admin/{endpoint}/{created['id']}", headers=auth_headers).status_code
        == 404
    )


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_get_not_found(client: TestClient, auth_headers, case) -> None:
    response = client.get(f"/api/v1/admin/{case[0]}/999999", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_validation_error(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    payload = _payload(case)
    payload.pop("name")

    response = client.post(f"/api/v1/admin/{endpoint}", json=payload, headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_list_pagination_and_search(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    for index in range(3):
        client.post(
            f"/api/v1/admin/{endpoint}",
            json=_payload(case, f"资源{index}") | {"description": ("关键字" if index == 1 else "")},
            headers=auth_headers,
        )

    page = client.get(f"/api/v1/admin/{endpoint}?page=1&page_size=2", headers=auth_headers).json()
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["page_size"] == 2
    assert len(page["items"]) == 2
    assert [item["name"] for item in page["items"]] == ["资源2", "资源1"]

    second_page = client.get(
        f"/api/v1/admin/{endpoint}?page=2&page_size=2", headers=auth_headers
    ).json()
    assert [item["name"] for item in second_page["items"]] == ["资源0"]

    searched = client.get(f"/api/v1/admin/{endpoint}?keyword=关键字", headers=auth_headers).json()
    assert searched["total"] == 1
    assert searched["items"][0]["name"] == "资源1"


@pytest.mark.parametrize("case", RESOURCE_CASES, ids=CASE_IDS)
def test_list_filter_is_enabled(client: TestClient, auth_headers, case) -> None:
    endpoint = case[0]
    client.post(f"/api/v1/admin/{endpoint}", json=_payload(case, "启用"), headers=auth_headers)
    client.post(
        f"/api/v1/admin/{endpoint}",
        json=_payload(case, "停用") | {"is_enabled": False},
        headers=auth_headers,
    )

    disabled = client.get(f"/api/v1/admin/{endpoint}?is_enabled=false", headers=auth_headers).json()

    assert disabled["total"] == 1
    assert disabled["items"][0]["name"] == "停用"


def test_paging_page_size_limit(client: TestClient, auth_headers) -> None:
    """接口层 page_size 上限为 100。"""
    assert (
        client.get("/api/v1/admin/skills?page=1&page_size=100", headers=auth_headers).status_code
        == 200
    )
    assert (
        client.get("/api/v1/admin/skills?page=1&page_size=150", headers=auth_headers).status_code
        == 422
    )


def test_paging_invalid(client: TestClient, auth_headers) -> None:
    assert client.get("/api/v1/admin/skills?page=0", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/admin/skills?page_size=0", headers=auth_headers).status_code == 422
