"""RBAC 权限资源目录、角色功能权限维护与防提权测试。"""

from uuid import UUID

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, list_roles, tenant_admin_client

PERMISSIONS_URL = "/api/v1/admin/permissions"
ROLES_URL = "/api/v1/admin/roles"
ADMIN_USERS_URL = "/api/v1/admin/admin-users"
OPERATOR_PASSWORD = "Role-perm-pass-123"


def _create_platform_account(
    client: TestClient,
    headers: dict[str, str],
    username: str,
    role_id: UUID,
) -> dict[str, str]:
    created = client.post(
        ADMIN_USERS_URL,
        json={
            "username": username,
            "password": OPERATOR_PASSWORD,
            "display_name": username,
            "role_id": role_id,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": OPERATOR_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _role_codes(client: TestClient, headers: dict[str, str], role_id: UUID) -> set[str]:
    response = client.get(f"{ROLES_URL}/{role_id}/permissions", headers=headers)
    assert response.status_code == 200, response.text
    return set(response.json()["codes"])


def _replace_permissions(
    client: TestClient,
    headers: dict[str, str],
    role_id: UUID,
    codes: list[str],
):
    return client.put(
        f"{ROLES_URL}/{role_id}/permissions", json={"codes": codes}, headers=headers
    )


def test_permission_catalog_covers_functional_resources(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(PERMISSIONS_URL, headers=auth_headers)

    assert response.status_code == 200, response.text
    items = response.json()
    codes = {item["code"] for item in items}
    assert {
        "system:console:access",
        "system:data:all",
        "menu:roles",
        "page:roles",
        "button:role:grant",
        "tool:create",
        "tool:read",
        "tool:update",
        "tool:delete",
    } <= codes
    assert {
        "system",
        "menu",
        "page",
        "button",
        "tool",
    } <= {item["category"] for item in items}


def test_tenant_catalog_excludes_platform_only_permissions(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    response = site.get(PERMISSIONS_URL, headers=headers)

    assert response.status_code == 200, response.text
    codes = {item["code"] for item in response.json()}
    assert "page:roles" in codes
    assert "menu:tenants" not in codes
    assert "page:tenants" not in codes


def test_role_permission_replace_add_and_remove(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    role = site.post(
        ROLES_URL, json={"code": "audit", "name": "审计"}, headers=headers
    ).json()

    replaced = _replace_permissions(
        site, headers, role["id"], ["system:console:access", "tool:read"]
    )
    assert replaced.status_code == 200, replaced.text
    assert set(replaced.json()["codes"]) == {"system:console:access", "tool:read"}

    added = site.post(
        f"{ROLES_URL}/{role['id']}/permissions",
        json={"codes": ["tool:update"]},
        headers=headers,
    )
    assert added.status_code == 200, added.text
    assert _role_codes(site, headers, role["id"]) == {
        "system:console:access",
        "tool:read",
        "tool:update",
    }

    removed = site.delete(
        f"{ROLES_URL}/{role['id']}/permissions/tool:read", headers=headers
    )
    assert removed.status_code == 204
    assert _role_codes(site, headers, role["id"]) == {
        "system:console:access",
        "tool:update",
    }

    missing = site.delete(
        f"{ROLES_URL}/{role['id']}/permissions/tool:read", headers=headers
    )
    assert missing.status_code == 404

    unknown = _replace_permissions(site, headers, role["id"], ["unknown:code"])
    assert unknown.status_code == 422

    platform_only = site.post(
        f"{ROLES_URL}/{role['id']}/permissions",
        json={"codes": ["page:tenants"]},
        headers=headers,
    )
    assert platform_only.status_code == 422

    audits = site.get(
        "/api/v1/admin/audit-logs",
        params={"action": "role.permissions.replaced"},
        headers=headers,
    )
    assert audits.status_code == 200, audits.text
    assert audits.json()["total"] >= 1


def test_superadmin_permissions_cannot_be_edited(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    superadmin_id = list_roles(site, headers)["superadmin"]["id"]

    response = _replace_permissions(site, headers, superadmin_id, ["system:console:access"])

    assert response.status_code == 422


def test_role_permission_grant_rejects_privilege_escalation(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    limited = client.post(
        ROLES_URL,
        json={"code": "tool-admin", "name": "工具管理员"},
        headers=auth_headers,
    ).json()
    granted = _replace_permissions(
        client,
        auth_headers,
        limited["id"],
        ["system:console:access", "button:role:grant", "tool:read"],
    )
    assert granted.status_code == 200, granted.text
    operator_headers = _create_platform_account(
        client, auth_headers, "tool-admin", limited["id"]
    )

    target = client.post(
        ROLES_URL, json={"code": "target", "name": "目标角色"}, headers=auth_headers
    ).json()

    denied = client.post(
        f"{ROLES_URL}/{target['id']}/permissions",
        json={"codes": ["tool:update"]},
        headers=operator_headers,
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"{ROLES_URL}/{target['id']}/permissions",
        json={"codes": ["tool:read"]},
        headers=operator_headers,
    )
    assert allowed.status_code == 200, allowed.text


def test_permission_changes_take_effect_immediately(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    role = client.post(
        ROLES_URL, json={"code": "tool-reader", "name": "工具只读"}, headers=auth_headers
    ).json()
    assert (
        _replace_permissions(
            client, auth_headers, role["id"], ["system:console:access", "tool:read"]
        ).status_code
        == 200
    )
    operator_headers = _create_platform_account(
        client, auth_headers, "tool-reader", role["id"]
    )
    assert client.get("/api/v1/admin/tools", headers=operator_headers).status_code == 200

    # 撤销权限后无需重新登录，下一次请求立即生效
    assert (
        client.delete(
            f"{ROLES_URL}/{role['id']}/permissions/tool:read", headers=auth_headers
        ).status_code
        == 204
    )
    assert client.get("/api/v1/admin/tools", headers=operator_headers).status_code == 403


def test_readonly_platform_role_is_denied_management_endpoints(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    roles = {
        item["code"]: item
        for item in client.get(ROLES_URL, headers=auth_headers).json()
    }
    viewer_headers = _create_platform_account(
        client, auth_headers, "platform-readonly", roles["viewer"]["id"]
    )

    assert client.get("/api/v1/admin/tools", headers=viewer_headers).status_code == 200
    assert client.get(ROLES_URL, headers=viewer_headers).status_code == 403
    assert client.get(ADMIN_USERS_URL, headers=viewer_headers).status_code == 403
    assert client.get("/api/v1/admin/tenants", headers=viewer_headers).status_code == 403
