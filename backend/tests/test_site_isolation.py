"""admin / user 站点路由隔离测试：两个站点互不暴露对方路由。"""

from fastapi.testclient import TestClient

TENANT_CODE = "acme"
TENANT_ADMIN_PASSWORD = "Tenant-password-123"
USER_API_TOKEN = "test-user-token-0123456789abcdef"


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


def test_user_site_serves_user_routes(
    client: TestClient,
    auth_headers: dict[str, str],
    user_tenant_client,
) -> None:
    _create_tenant(client, auth_headers)
    acme = user_tenant_client(TENANT_CODE)

    response = acme.get("/api/v1/user/me", headers={"Authorization": f"Bearer {USER_API_TOKEN}"})

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "user"


def test_user_site_health(user_client: TestClient) -> None:
    assert user_client.get("/health/live").status_code == 200
