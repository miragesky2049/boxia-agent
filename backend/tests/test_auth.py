"""管理员认证、令牌轮换、锁定与 RBAC 测试。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.database import get_engine
from internal.infrastructure.security.password import hash_password

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin-password-123"
ADMIN_LOGIN = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
ME_URL = "/api/v1/admin/auth/me"


def _login(client: TestClient, password: str = ADMIN_PASSWORD) -> dict:
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": ADMIN_USERNAME, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _encode(claims: dict, secret: str | None = None) -> str:
    """按真实令牌结构补齐 claims 后签名。"""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": "1",
        "username": ADMIN_USERNAME,
        "role": "superadmin",
        "scope": "admin",
        "sid": str(uuid4()),
        "ver": 1,
        "jti": str(uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "type": "access",
        **claims,
    }
    return jwt.encode(payload, secret or settings.jwt_secret.get_secret_value(), algorithm="HS256")


def _insert_user(username: str, role: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO admin_users "
                "(username, password_hash, display_name, role, must_change_password) "
                "VALUES (:username, :hash, :display_name, :role, FALSE)"
            ),
            {
                "username": username,
                "hash": hash_password(ADMIN_PASSWORD),
                "display_name": username,
                "role": role,
            },
        )


def test_login_success(client: TestClient) -> None:
    body = _login(client)

    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_minutes * 60
    assert body["refresh_token"].startswith("bxt_")
    assert body["refresh_expires_in"] > 0
    assert body["user"]["username"] == ADMIN_USERNAME
    assert body["user"]["role"] == "superadmin"
    assert body["user"]["must_change_password"] is False


def test_login_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_login_unknown_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": "nobody", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_login_inactive_user(client: TestClient) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE admin_users SET is_active = FALSE WHERE username = 'admin'"))

    response = client.post("/api/v1/admin/auth/login", json=ADMIN_LOGIN)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_login_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/admin/auth/login", json={"username": "", "password": ""})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_login_lockout(client: TestClient) -> None:
    settings = get_settings()
    for _ in range(settings.login_max_attempts):
        response = client.post(
            "/api/v1/admin/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong"}
        )
        assert response.status_code in (401, 429)

    locked = client.post("/api/v1/admin/auth/login", json=ADMIN_LOGIN)
    assert locked.status_code == 429
    assert locked.json()["code"] == "ACCOUNT_LOCKED"
    assert int(locked.headers["Retry-After"]) > 0


def test_me_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(ME_URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["username"] == ADMIN_USERNAME
    assert response.json()["role"] == "superadmin"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic admin"},
    ],
    ids=["missing", "malformed", "empty", "wrong-scheme"],
)
def test_me_unauthorized(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get(ME_URL, headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_me_expired_token(client: TestClient) -> None:
    now = datetime.now(UTC)
    token = _encode({"iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)})

    response = client.get(ME_URL, headers=_bearer(token))

    assert response.status_code == 401
    assert "过期" in response.json()["detail"]


def test_me_wrong_token_type(client: TestClient) -> None:
    response = client.get(ME_URL, headers=_bearer(_encode({"type": "refresh"})))

    assert response.status_code == 401


def test_me_wrong_secret(client: TestClient) -> None:
    token = _encode({}, secret="someone-elses-secret-0123456789abcdef")

    response = client.get(ME_URL, headers=_bearer(token))

    assert response.status_code == 401


def test_me_deleted_admin(client: TestClient) -> None:
    response = client.get(ME_URL, headers=_bearer(_encode({"sub": "999"})))

    assert response.status_code == 401


def test_me_token_version_mismatch(client: TestClient, auth_headers: dict[str, str]) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE admin_users SET token_version = token_version + 1"))

    response = client.get(ME_URL, headers=auth_headers)

    assert response.status_code == 401


def test_logout_invalidates_tokens(client: TestClient) -> None:
    tokens = _login(client)
    headers = _bearer(tokens["access_token"])
    assert client.get(ME_URL, headers=headers).status_code == 200

    assert client.post("/api/v1/admin/auth/logout", headers=headers).status_code == 204

    assert client.get(ME_URL, headers=headers).status_code == 401
    refreshed = client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401


def test_refresh_rotation_and_replay_detection(client: TestClient) -> None:
    first = _login(client)
    rotated = client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]

    replay = client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401

    # 重放检测撤销整族：最新刷新令牌与访问令牌同时失效
    after_replay = client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after_replay.status_code == 401
    assert client.get(ME_URL, headers=_bearer(second["access_token"])).status_code == 401


def test_change_password_revokes_sessions(client: TestClient) -> None:
    tokens = _login(client)
    headers = _bearer(tokens["access_token"])
    new_password = "New-password-456"

    response = client.post(
        "/api/v1/admin/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": new_password},
        headers=headers,
    )
    assert response.status_code == 204, response.text

    assert client.get(ME_URL, headers=headers).status_code == 401
    old_login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert old_login.status_code == 401
    _login(client, password=new_password)


def test_change_password_rejects_weak_password(client: TestClient) -> None:
    tokens = _login(client)
    response = client.post(
        "/api/v1/admin/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "short"},
        headers=_bearer(tokens["access_token"]),
    )

    assert response.status_code == 422


def test_viewer_cannot_write(client: TestClient) -> None:
    _insert_user("viewer", "viewer")
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": "viewer", "password": ADMIN_PASSWORD}
    )
    headers = _bearer(response.json()["access_token"])

    assert client.get("/api/v1/admin/skills", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/v1/admin/skills",
            json={"name": "只读", "description": "", "content": "", "config": {}},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit-logs", headers=headers).status_code == 403


def test_audit_logs_record_events(client: TestClient, auth_headers: dict[str, str]) -> None:
    _login(client)
    response = client.get("/api/v1/admin/audit-logs?action=auth.login", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert body["items"][0]["action"] == "auth.login"


def test_legacy_api_alias(client: TestClient) -> None:
    response = client.post("/api/admin/auth/login", json=ADMIN_LOGIN)

    assert response.status_code == 200
