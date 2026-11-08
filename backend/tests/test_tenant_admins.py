"""平台管理员跨租户管理管理员账号接口测试。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import create_tenant

TENANT_ADMIN_PASSWORD = "Tenant-password-123"
OPERATOR_PASSWORD = "Operator-pass-456"
RESET_PASSWORD = "Reset-pass-789"


def _admins_url(tenant_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/admins"


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_operator(
    client: TestClient, headers: dict[str, str], tenant_id: str, username: str = "tenant-op"
) -> dict:
    response = client.post(
        _admins_url(tenant_id),
        json={
            "username": username,
            "password": OPERATOR_PASSWORD,
            "display_name": "租户运营",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_list_tenant_admins_contains_seed_admin(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    tenant = create_tenant(client, auth_headers, code="acme-list", name="Acme 列表")

    response = client.get(_admins_url(tenant["id"]), headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["username"] == "acme-list-admin"
    assert body["items"][0]["tenant_id"] == tenant["id"]


def test_create_update_reset_password_delete_tenant_admin(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="acme-crud", name="Acme CRUD")
    created = _create_operator(client, auth_headers, tenant["id"])

    listed = client.get(f"{_admins_url(tenant['id'])}?keyword=tenant-op", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    updated = client.patch(
        f"{_admins_url(tenant['id'])}/{created['id']}",
        json={"display_name": "改名运营"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "改名运营"

    reset = client.post(
        f"{_admins_url(tenant['id'])}/{created['id']}/password",
        json={"new_password": RESET_PASSWORD},
        headers=auth_headers,
    )
    assert reset.status_code == 204, reset.text

    acme = tenant_client("acme-crud")
    operator_headers = _login(acme, "tenant-op", RESET_PASSWORD)
    me = acme.get("/api/v1/admin/auth/me", headers=operator_headers)
    assert me.status_code == 200, me.text

    deleted = client.delete(f"{_admins_url(tenant['id'])}/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text
    listed_after_delete = client.get(_admins_url(tenant["id"]), headers=auth_headers)
    assert listed_after_delete.json()["total"] == 1


def test_list_tenant_admins_404_for_unknown_tenant(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(_admins_url(str(uuid4())), headers=auth_headers)
    assert response.status_code == 404, response.text


def test_create_tenant_admin_rejects_role_id_field(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """产品级新建管理员不再接受 role_id，角色由服务端固定绑定超级管理员。"""
    tenant = create_tenant(client, auth_headers, code="acme-rid", name="Acme 角色字段")

    response = client.post(
        _admins_url(tenant["id"]),
        json={
            "username": "with-role-id",
            "password": OPERATOR_PASSWORD,
            "display_name": "带角色",
            "role_id": str(uuid4()),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text


def test_create_tenant_admin_binds_superadmin_role(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    tenant = create_tenant(client, auth_headers, code="acme-sa", name="Acme 超管绑定")

    created = _create_operator(client, auth_headers, tenant["id"], username="sa-op")

    assert created["role_code"] == "superadmin"
    assert created["role_name"] == "超级管理员"


def test_tenant_user_cannot_call_tenant_admins(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="acme-deny", name="Acme 拒绝")
    acme = tenant_client("acme-deny")
    tokens = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": "acme-deny-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert tokens.status_code == 200, tokens.text
    tenant_headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    assert acme.get(_admins_url(tenant["id"]), headers=tenant_headers).status_code == 403
    assert (
        acme.post(
            _admins_url(tenant["id"]),
            json={
                "username": "ghost",
                "password": OPERATOR_PASSWORD,
                "display_name": "幽灵",
            },
            headers=tenant_headers,
        ).status_code
        == 403
    )
