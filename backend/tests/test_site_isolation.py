"""admin / user 站点路由隔离测试：两个站点互不暴露对方路由。"""

from fastapi.testclient import TestClient

TENANT_CODE = "acme"
TENANT_ADMIN_PASSWORD = "Tenant-password-123"
USER_USERNAME = "acme-viewer"
USER_PASSWORD = "User-password-123"


def _create_tenant(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "code": TENANT_CODE,
            "name": "Acme 公司",
            "admin_username": "acme-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": "Acme 管理员",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_admin_site_excludes_user_routes(client: TestClient) -> None:
    assert client.get("/api/v1/user/me").status_code == 404


def test_admin_site_keeps_public_routes(client: TestClient) -> None:
    response = client.get("/api/v1/public/context")

    assert response.status_code == 200
    assert response.json()["scope"] == "platform"


def test_user_site_excludes_admin_and_public_routes(
    user_client: TestClient, user_tenant_client
) -> None:
    for path in ("/api/v1/admin/auth/login", "/api/v1/admin/users", "/api/v1/public/context"):
        assert user_client.get(path).status_code == 404

    acme = user_tenant_client(TENANT_CODE)
    assert acme.get("/api/v1/admin/auth/login").status_code == 404
    assert acme.get("/api/v1/public/context").status_code == 404


def _create_user(tenant_client) -> None:
    """以租户超管身份创建只读最终用户。"""
    acme = tenant_client(TENANT_CODE)
    login = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": "acme-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    roles = acme.get("/api/v1/admin/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    viewer = next(item for item in roles.json() if item["code"] == "viewer")

    created = acme.post(
        "/api/v1/admin/users",
        json={
            "username": USER_USERNAME,
            "password": USER_PASSWORD,
            "display_name": "只读用户",
            "role_ids": [viewer["id"]],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text


def test_user_site_serves_user_routes(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_client,
    user_tenant_client,
    user_login_headers,
) -> None:
    _create_tenant(client, auth_headers)
    _create_user(tenant_client)
    acme = user_tenant_client(TENANT_CODE)
    headers = user_login_headers(TENANT_CODE, USER_USERNAME, USER_PASSWORD)

    response = acme.get("/api/v1/user/me", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == USER_USERNAME
    assert body["role_code"] == "viewer"


def test_user_routes_require_login(
    client: TestClient,
    auth_headers: dict[str, str],
    user_tenant_client,
) -> None:
    _create_tenant(client, auth_headers)
    acme = user_tenant_client(TENANT_CODE)

    assert acme.get("/api/v1/user/me").status_code == 401


def test_user_site_health(user_client: TestClient) -> None:
    assert user_client.get("/health/live").status_code == 200
