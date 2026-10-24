"""租户角色管理：初始化、CRUD、系统角色保护与租户隔离。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    TENANT_ADMIN_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)


def test_tenant_roles_initialized_and_custom_crud(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    roles = list_roles(site, headers)
    assert {"superadmin", "admin", "viewer"} <= set(roles)
    assert all(item["is_system"] for item in roles.values())
    assert roles["superadmin"]["system_role"] == "superadmin"

    created = site.post(
        "/api/v1/admin/roles",
        json={
            "code": "sales",
            "name": "销售",
            "description": "销售角色",
            "system_role": "viewer",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["is_system"] is False
    assert role["is_active"] is True

    duplicate = site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售二部", "system_role": "viewer"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    updated = site.patch(
        f"/api/v1/admin/roles/{role['id']}",
        json={"name": "销售一组", "description": "调整后"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "销售一组"

    deleted = site.delete(f"/api/v1/admin/roles/{role['id']}", headers=headers)
    assert deleted.status_code == 204
    assert "sales" not in list_roles(site, headers)


def test_system_role_cannot_be_disabled_or_deleted(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    viewer = list_roles(site, headers)["viewer"]

    disabled = site.patch(
        f"/api/v1/admin/roles/{viewer['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert disabled.status_code == 422

    deleted = site.delete(f"/api/v1/admin/roles/{viewer['id']}", headers=headers)
    assert deleted.status_code == 422


def test_referenced_role_cannot_be_deleted(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    custom = site.post(
        "/api/v1/admin/roles",
        json={"code": "support", "name": "客服", "system_role": "viewer"},
        headers=headers,
    ).json()
    create_user(site, headers, role_id=custom["id"])

    deleted = site.delete(f"/api/v1/admin/roles/{custom['id']}", headers=headers)
    assert deleted.status_code == 409


def test_platform_manages_own_roles_only(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)

    created = client.post(
        "/api/v1/admin/roles",
        json={"code": "ops", "name": "平台运营", "system_role": "viewer"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] is None

    listed = client.get("/api/v1/admin/roles", headers=auth_headers)
    assert listed.status_code == 200
    codes = {item["code"] for item in listed.json()}
    assert {"superadmin", "admin", "viewer", "ops"} <= codes
    assert all(item["tenant_id"] is None for item in listed.json())

    tenant = client.get("/api/v1/admin/tenants", headers=auth_headers).json()
    tenant_item = next(item for item in tenant["items"] if item["code"] == "acme")
    forbidden = client.get(
        "/api/v1/admin/roles",
        params={"tenant_id": tenant_item["id"]},
        headers=auth_headers,
    )
    assert forbidden.status_code == 403


def test_roles_are_tenant_isolated(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    globex = create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    acme_site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售", "system_role": "viewer"},
        headers=acme_headers,
    )
    assert "sales" in list_roles(acme_site, acme_headers)
    assert "sales" not in list_roles(globex_site, globex_headers)

    forbidden = acme_site.get(
        "/api/v1/admin/roles",
        params={"tenant_id": globex["id"]},
        headers=acme_headers,
    )
    assert forbidden.status_code == 403


def test_viewer_admin_can_read_but_not_manage_roles(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    viewer = list_roles(site, headers)["viewer"]

    created_user = site.post(
        "/api/v1/admin/users",
        json={
            "username": "acme-viewer-admin",
            "password": TENANT_ADMIN_PASSWORD,
            "display_name": "只读管理员",
            "role_ids": [viewer["id"]],
        },
        headers=headers,
    )
    assert created_user.status_code == 201, created_user.text

    login = site.post(
        "/api/v1/admin/auth/login",
        json={"username": "acme-viewer-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert site.get("/api/v1/admin/roles", headers=viewer_headers).status_code == 200
    denied = site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售", "system_role": "viewer"},
        headers=viewer_headers,
    )
    assert denied.status_code == 403
