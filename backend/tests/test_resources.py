"""统一资源（resource）端点测试：CRUD、平台授权与租户可见性。"""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client


def _tool_payload(name: str = "示例工具", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "tool",
        "name": name,
        "config": {"url": "https://example.com/api", "method": "GET"},
    }
    payload.update(extra)
    return payload


def _create_resource(client: TestClient, headers: dict[str, str], payload: dict[str, Any]) -> str:
    response = client.post("/api/v1/admin/resources", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["resource_id"]


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/resources").status_code == 401
    assert (
        client.post("/api/v1/admin/resources", json=_tool_payload()).status_code == 401
    )


def test_create_and_get(client: TestClient, auth_headers) -> None:
    resource_id = _create_resource(client, auth_headers, _tool_payload())

    detail = client.get(f"/api/v1/admin/resources/{resource_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == resource_id
    assert body["type"] == "tool"
    assert body["owner_type"] == "platform"
    assert body["owner_id"] is None
    assert body["name"] == "示例工具"
    assert body["config"] == {"url": "https://example.com/api", "method": "GET"}
    assert body["is_enabled"] is True
    assert body["is_deprecated"] is False
    assert body["version"] == 1
    assert body["created_at"]


def test_list_resources_with_filters(client: TestClient, auth_headers) -> None:
    _create_resource(client, auth_headers, _tool_payload("工具一"))
    _create_resource(
        client,
        auth_headers,
        {"type": "prompt", "name": "提示词一", "config": {}},
    )

    all_items = client.get("/api/v1/admin/resources", headers=auth_headers)
    assert all_items.status_code == 200, all_items.text
    assert {item["name"] for item in all_items.json()} == {"工具一", "提示词一"}

    tools = client.get(
        "/api/v1/admin/resources", params={"type": "tool"}, headers=auth_headers
    )
    assert [item["name"] for item in tools.json()] == ["工具一"]


def test_admin_list_includes_disabled(client: TestClient, auth_headers) -> None:
    _create_resource(
        client, auth_headers, _tool_payload("停用工具", is_enabled=False)
    )

    items = client.get("/api/v1/admin/resources", headers=auth_headers).json()
    assert [item["name"] for item in items] == ["停用工具"]


def test_update_resource(client: TestClient, auth_headers) -> None:
    resource_id = _create_resource(client, auth_headers, _tool_payload("旧名称"))

    updated = client.patch(
        f"/api/v1/admin/resources/{resource_id}",
        json={
            "name": "新名称",
            "config": {"method": "POST"},
            "is_enabled": False,
            "is_deprecated": True,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"ok": True}

    body = client.get(
        f"/api/v1/admin/resources/{resource_id}", headers=auth_headers
    ).json()
    assert body["name"] == "新名称"
    assert body["config"] == {"method": "POST"}
    assert body["is_enabled"] is False
    assert body["is_deprecated"] is True


def test_delete_resource(client: TestClient, auth_headers) -> None:
    resource_id = _create_resource(client, auth_headers, _tool_payload())

    deleted = client.delete(
        f"/api/v1/admin/resources/{resource_id}", headers=auth_headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"ok": True}
    assert (
        client.get(
            f"/api/v1/admin/resources/{resource_id}", headers=auth_headers
        ).status_code
        == 404
    )


def test_get_not_found(client: TestClient, auth_headers) -> None:
    response = client.get(
        f"/api/v1/admin/resources/{uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_validation_errors(client: TestClient, auth_headers) -> None:
    invalid_type = client.post(
        "/api/v1/admin/resources",
        json=_tool_payload(type="widget"),
        headers=auth_headers,
    )
    assert invalid_type.status_code == 422, invalid_type.text

    empty_name = client.post(
        "/api/v1/admin/resources",
        json=_tool_payload(name="   "),
        headers=auth_headers,
    )
    assert empty_name.status_code == 422, empty_name.text

    tenant_without_owner = client.post(
        "/api/v1/admin/resources",
        json=_tool_payload(owner_type="tenant"),
        headers=auth_headers,
    )
    assert tenant_without_owner.status_code == 422, tenant_without_owner.text


def test_update_not_found(client: TestClient, auth_headers) -> None:
    assert (
        client.patch(
            f"/api/v1/admin/resources/{uuid4()}",
            json={"name": "不存在"},
            headers=auth_headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/admin/resources/{uuid4()}", headers=auth_headers
        ).status_code
        == 404
    )


def test_tenant_admin_cannot_manage_resources(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    assert (
        site.post(
            "/api/v1/admin/resources", json=_tool_payload(), headers=headers
        ).status_code
        == 403
    )


def test_platform_grant_and_tenant_visibility(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    resource_id = _create_resource(client, auth_headers, _tool_payload("平台工具"))
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    def _visible_ids() -> set[str]:
        response = site.get("/api/v1/admin/my-resources", headers=headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()}

    assert resource_id not in _visible_ids()

    granted = client.post(
        f"/api/v1/admin/resources/{resource_id}/grants",
        json={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert granted.status_code == 201, granted.text

    grants = client.get(
        f"/api/v1/admin/resources/{resource_id}/grants", headers=auth_headers
    )
    assert grants.status_code == 200, grants.text
    assert [item["tenant_id"] for item in grants.json()] == [tenant["id"]]

    assert resource_id in _visible_ids()

    revoked = client.delete(
        f"/api/v1/admin/resources/{resource_id}/grants/{tenant['id']}",
        headers=auth_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert resource_id not in _visible_ids()


def test_grant_only_platform_resource(
    client: TestClient, auth_headers
) -> None:
    tenant_id = uuid4()
    resource_id = _create_resource(
        client,
        auth_headers,
        _tool_payload("租户工具", owner_type="tenant", owner_id=str(tenant_id)),
    )

    response = client.post(
        f"/api/v1/admin/resources/{resource_id}/grants",
        json={"tenant_id": str(tenant_id)},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
