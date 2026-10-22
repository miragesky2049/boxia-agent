"""多租户隔离测试：子域名识别、账号隔离与产品级资源只读复用。"""

from fastapi.testclient import TestClient

TENANT_ADMIN_PASSWORD = "Tenant-password-123"
TENANT_A = "acme"
TENANT_B = "globex"


def _create_tenant(client: TestClient, headers: dict[str, str], code: str, name: str) -> dict:
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "code": code,
            "name": name,
            "admin_username": f"{code}-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": f"{name}管理员",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(tenant_client: TestClient, username: str, password: str = TENANT_ADMIN_PASSWORD) -> dict:
    response = tenant_client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _skill_payload(name: str) -> dict:
    return {"name": name, "description": "", "content": "", "config": {}}


def test_platform_context(client: TestClient) -> None:
    response = client.get("/api/v1/public/context")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "platform"
    assert body["tenant"] is None
    assert body["root_domain"] == "example.com"
    assert body["platform_admin_subdomain"] == "adminsystem"
    assert body["platform_name"] == "Agent运营管理平台"


def test_tenant_context_and_login(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    created = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)

    public_context = acme.get("/api/v1/public/context")
    assert public_context.status_code == 200
    assert public_context.json()["scope"] == "tenant"
    assert public_context.json()["tenant"]["code"] == TENANT_A

    tokens = _login(acme, f"{TENANT_A}-admin")
    assert tokens["user"]["tenant_id"] == created["id"]
    assert tokens["user"]["is_platform"] is False

    context = acme.get("/api/v1/admin/context", headers=_bearer(tokens["access_token"]))
    assert context.status_code == 200, context.text
    assert context.json()["scope"] == "tenant"
    assert context.json()["user"]["username"] == f"{TENANT_A}-admin"


def test_platform_account_cannot_login_on_tenant_domain(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)

    response = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert response.status_code == 401


def test_tenant_admin_cannot_manage_tenants(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tokens = _login(acme, f"{TENANT_A}-admin")
    headers = _bearer(tokens["access_token"])

    assert acme.get("/api/v1/admin/tenants", headers=headers).status_code == 403
    response = acme.post(
        "/api/v1/admin/tenants",
        json={
            "code": "other",
            "name": "Other",
            "admin_username": "other-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_cross_scope_token_rejected(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    assert globex.get("/api/v1/admin/auth/me", headers=acme_headers).status_code == 401


def test_platform_resource_visible_but_readonly_for_tenant(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    platform_skill = client.post(
        "/api/v1/admin/skills", json=_skill_payload("产品级技能"), headers=auth_headers
    )
    assert platform_skill.status_code == 201
    platform_id = platform_skill.json()["id"]
    assert platform_skill.json()["is_platform"] is True

    listed = acme.get("/api/v1/admin/skills?page_size=100", headers=tenant_headers)
    assert listed.status_code == 200
    assert platform_id in [item["id"] for item in listed.json()["items"]]

    assert (
        acme.get(f"/api/v1/admin/skills/{platform_id}", headers=tenant_headers).status_code == 200
    )
    update = acme.put(
        f"/api/v1/admin/skills/{platform_id}",
        json=_skill_payload("篡改"),
        headers=tenant_headers,
    )
    assert update.status_code == 403
    assert (
        acme.delete(f"/api/v1/admin/skills/{platform_id}", headers=tenant_headers).status_code
        == 403
    )

    # 产品级列表只展示产品级资源
    platform_listed = client.get("/api/v1/admin/skills?page_size=100", headers=auth_headers)
    assert [item["id"] for item in platform_listed.json()["items"]] == [platform_id]


def test_tenant_resources_isolated(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    acme_tenant = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    globex_headers = _bearer(_login(globex, f"{TENANT_B}-admin")["access_token"])

    created = acme.post(
        "/api/v1/admin/skills", json=_skill_payload("租户技能"), headers=acme_headers
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    assert created.json()["tenant_id"] == acme_tenant["id"]
    assert created.json()["is_platform"] is False

    assert globex.get(f"/api/v1/admin/skills/{skill_id}", headers=globex_headers).status_code == 404
    assert (
        globex.get("/api/v1/admin/skills?page_size=100", headers=globex_headers).json()["total"]
        == 0
    )


def test_same_name_across_tenants(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    globex_headers = _bearer(_login(globex, f"{TENANT_B}-admin")["access_token"])

    assert (
        acme.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=acme_headers
        ).status_code
        == 201
    )
    assert (
        globex.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=globex_headers
        ).status_code
        == 201
    )
    # 租户仍不能与产品级资源重名
    assert (
        client.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=auth_headers
        ).status_code
        == 201
    )
    assert (
        acme.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=acme_headers
        ).status_code
        == 409
    )


def test_tenant_users_scoped(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    created = acme.post(
        "/api/v1/admin/users",
        json={
            "username": "operator",
            "password": "Strong-password-456",
            "display_name": "运营",
            "role": "admin",
        },
        headers=tenant_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] is not None

    listed = acme.get("/api/v1/admin/users?page_size=100", headers=tenant_headers)
    assert {item["username"] for item in listed.json()["items"]} == {
        f"{TENANT_A}-admin",
        "operator",
    }
    assert (
        acme.get("/api/v1/admin/users?all_tenants=true", headers=tenant_headers).status_code == 403
    )

    all_users = client.get(
        "/api/v1/admin/users?all_tenants=true&page_size=100", headers=auth_headers
    )
    assert all_users.status_code == 200
    assert all_users.json()["total"] == 3


def test_create_user_with_unknown_tenant_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/admin/users",
        json={
            "username": "ghost-admin",
            "password": "Strong-password-456",
            "display_name": "幽灵账号",
            "role": "admin",
            "tenant_id": 999999,
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_tenant_login_failure_audited_in_tenant_scope(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    failed = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": f"{TENANT_A}-admin", "password": "Wrong-password-999"},
    )
    assert failed.status_code == 401

    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    logs = acme.get(
        "/api/v1/admin/audit-logs?action=auth.login_failed&page_size=100",
        headers=tenant_headers,
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] == 1


def test_disabled_tenant_blocked(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    created = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tokens = _login(acme, f"{TENANT_A}-admin")

    disabled = client.patch(
        f"/api/v1/admin/tenants/{created['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    assert acme.get("/api/v1/public/context").status_code == 403
    assert (
        acme.get("/api/v1/admin/auth/me", headers=_bearer(tokens["access_token"])).status_code
        == 403
    )
