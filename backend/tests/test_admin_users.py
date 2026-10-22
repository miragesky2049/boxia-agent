"""管理员账号管理、角色变更与审计中间件测试。"""

from fastapi.testclient import TestClient

USERS_URL = "/api/v1/admin/users"
OPERATOR_PASSWORD = "Editor-pass-123"


def _create_operator(client: TestClient, headers: dict[str, str], role: str = "admin") -> dict:
    response = client.post(
        USERS_URL,
        json={
            "username": "operator",
            "password": OPERATOR_PASSWORD,
            "display_name": "运营",
            "role": role,
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
    assert response.json()["items"][0]["role"] == "superadmin"


def test_create_user_requires_password_change(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create_operator(client, auth_headers)

    assert created["must_change_password"] is True
    assert created["role"] == "admin"
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)
    assert client.get("/api/v1/admin/skills", headers=operator_headers).status_code == 200


def test_create_duplicate_username(client: TestClient, auth_headers: dict[str, str]) -> None:
    _create_operator(client, auth_headers)
    response = client.post(
        USERS_URL,
        json={
            "username": "operator",
            "password": OPERATOR_PASSWORD,
            "display_name": "重复",
            "role": "admin",
        },
        headers=auth_headers,
    )

    assert response.status_code == 409


def test_create_user_rejects_weak_password(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        USERS_URL,
        json={"username": "weakuser", "password": "weakweakweak", "display_name": "弱口令"},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_demote_user_takes_effect_immediately(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create_operator(client, auth_headers)
    operator_headers = _login(client, "operator", OPERATOR_PASSWORD)

    response = client.patch(
        f"{USERS_URL}/{created['id']}", json={"role": "viewer"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"
    assert (
        client.post(
            "/api/v1/admin/skills",
            json={"name": "降级后写入", "description": "", "content": "", "config": {}},
            headers=operator_headers,
        ).status_code
        == 403
    )


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


def test_write_request_is_audited(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/admin/skills",
        json={"name": "审计技能", "description": "", "content": "", "config": {}},
        headers=auth_headers,
    )
    assert created.status_code == 201

    response = client.get("/api/v1/admin/audit-logs?action=post.skills", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1
    assert response.json()["items"][0]["resource_type"] == "skills"
