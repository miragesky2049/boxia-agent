"""管理员账号管理、角色变更与审计中间件测试。"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.database import get_engine
from tests.helpers import create_tenant

USERS_URL = "/api/v1/admin/admin-users"
OPERATOR_PASSWORD = "Editor-pass-123"


def _role_id(client: TestClient, headers: dict[str, str], code: str) -> str:
    roles = client.get("/api/v1/admin/roles", headers=headers).json()
    return next(item["id"] for item in roles if item["code"] == code)


def _create_operator(
    client: TestClient, headers: dict[str, str], role_code: str = "admin"
) -> dict:
    response = client.post(
        USERS_URL,
        json={
            "username": "operator",
            "password": OPERATOR_PASSWORD,
            "display_name": "运营",
            "role_id": _role_id(client, headers, role_code),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_list_users(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(USERS_URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["role_code"] == "superadmin"


def test_create_user_requires_password_change(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create_operator(client, auth_headers)

    assert created["must_change_password"] is True
    assert created["role_code"] == "admin"
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)
    assert client.get("/api/v1/admin/resources", headers=operator_headers).status_code == 200


def test_create_duplicate_username(client: TestClient, auth_headers: dict[str, str]) -> None:
    _create_operator(client, auth_headers)
    response = client.post(
        USERS_URL,
        json={
            "username": "operator",
            "password": OPERATOR_PASSWORD,
            "display_name": "重复",
            "role_id": _role_id(client, auth_headers, "admin"),
        },
        headers=auth_headers,
    )

    assert response.status_code == 409


def test_create_user_rejects_weak_password(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        USERS_URL,
        json={
            "username": "weakuser",
            "password": "weakweakweak",
            "display_name": "弱口令",
            "role_id": _role_id(client, auth_headers, "admin"),
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_demote_user_takes_effect_immediately(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create_operator(client, auth_headers)
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)

    restricted = client.post(
        "/api/v1/admin/roles",
        json={"code": "restricted", "name": "受限角色"},
        headers=auth_headers,
    )
    assert restricted.status_code == 201, restricted.text
    restricted_id = restricted.json()["id"]
    replaced = client.put(
        f"/api/v1/admin/roles/{restricted_id}/permissions",
        json={"codes": ["system:console:access"]},
        headers=auth_headers,
    )
    assert replaced.status_code == 200, replaced.text

    def _menus() -> list[str]:
        response = client.get("/api/v1/admin/context", headers=operator_headers)
        assert response.status_code == 200, response.text
        return response.json()["menus"]

    assert "resources" in _menus()

    response = client.patch(
        f"{USERS_URL}/{created['id']}",
        json={"role_id": restricted_id},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["role_code"] == "restricted"
    # 降级后无需重新登录，下一次请求可见菜单立即收敛
    assert _menus() == []


def test_disable_user_revokes_sessions(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = _create_operator(client, auth_headers)
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)

    response = client.patch(
        f"{USERS_URL}/{created['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert response.status_code == 200
    assert client.get("/api/v1/admin/auth/me", headers=operator_headers).status_code == 401


def test_cannot_disable_self(client: TestClient, auth_headers: dict[str, str]) -> None:
    me = client.get("/api/v1/admin/auth/me", headers=auth_headers).json()

    response = client.patch(
        f"{USERS_URL}/{me['id']}", json={"is_active": False}, headers=auth_headers
    )

    assert response.status_code == 422


def test_reset_password_revokes_sessions(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = _create_operator(client, auth_headers)
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)

    response = client.post(
        f"{USERS_URL}/{created['id']}/password",
        json={"new_password": "Reset-pass-789"},
        headers=auth_headers,
    )
    assert response.status_code == 204
    assert client.get("/api/v1/admin/auth/me", headers=operator_headers).status_code == 401
    assert _login(client, "operator", "Reset-pass-789")


def test_platform_account_binds_platform_role(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    roles = {
        item["code"]: item
        for item in client.get("/api/v1/admin/roles", headers=auth_headers).json()
    }
    created = client.post(
        USERS_URL,
        json={
            "username": "platform-viewer",
            "password": OPERATOR_PASSWORD,
            "display_name": "平台只读",
            "role_id": roles["viewer"]["id"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["role_code"] == "viewer"
    assert created.json()["role_id"] == roles["viewer"]["id"]

    # 平台只读账号仍可登录，资源范围由角色授权决定（此时为空）
    operator_headers = _login(client, "platform-viewer", OPERATOR_PASSWORD)
    listed = client.get("/api/v1/admin/apps", headers=operator_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 0


def test_platform_account_rejects_tenant_role(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    tenant = create_tenant(client, auth_headers)
    with get_engine().connect() as conn:
        tenant_viewer_id = conn.execute(
            text("SELECT id FROM roles WHERE tenant_id = :tenant_id AND code = 'viewer'"),
            {"tenant_id": tenant["id"]},
        ).scalar_one()

    response = client.post(
        USERS_URL,
        json={
            "username": "platform-bad-role",
            "password": OPERATOR_PASSWORD,
            "display_name": "错误绑定",
            "role_id": str(tenant_viewer_id),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_write_request_is_audited(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/admin/resources",
        json={
            "type": "tool",
            "name": "审计工具",
            "config": {"url": "https://example.com/api", "method": "GET"},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201

    response = client.get("/api/v1/admin/audit-logs?action=post.resources", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1
    assert response.json()["items"][0]["resource_type"] == "resources"
