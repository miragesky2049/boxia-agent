"""最终用户管理：CRUD、角色绑定、登录会话与失效控制。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)


def _login_user(user_tenant_client, username: str, password: str = USER_PASSWORD):
    site = user_tenant_client("acme")
    return site.post(
        "/api/v1/user/auth/login",
        json={"username": username, "password": password},
    )


def test_user_crud_and_duplicate_username(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    created = create_user(
        site,
        headers,
        username="alice",
        role_id=roles["viewer"]["id"],
        display_name="Alice",
    )
    assert created["role_id"] == roles["viewer"]["id"]

    duplicate = site.post(
        "/api/v1/admin/users",
        json={
            "username": "alice",
            "password": USER_PASSWORD,
            "display_name": "重复",
            "role_ids": [roles["viewer"]["id"]],
        },
        headers=headers,
    )
    assert duplicate.status_code == 409

    listed = site.get("/api/v1/admin/users", headers=headers)
    assert listed.status_code == 200
    assert {item["username"] for item in listed.json()["items"]} == {"alice", "acme-admin"}
    assert "password_hash" not in listed.json()["items"][0]

    updated = site.patch(
        f"/api/v1/admin/users/{created['id']}",
        json={"display_name": "Alice 2"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Alice 2"

    deleted = site.delete(f"/api/v1/admin/users/{created['id']}", headers=headers)
    assert deleted.status_code == 204
    assert site.get("/api/v1/admin/users", headers=headers).json()["total"] == 1


def test_user_can_be_created_without_role(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    response = site.post(
        "/api/v1/admin/users",
        json={
            "username": "norole",
            "password": USER_PASSWORD,
            "display_name": "无角色用户",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["role_id"] is None
    assert created["role_ids"] == []

    listed = site.get("/api/v1/admin/users", headers=headers)
    assert listed.status_code == 200
    assert "norole" in {item["username"] for item in listed.json()["items"]}

    # 未分配角色前不可登录，需先在「用户授权」中授权
    assert _login_user(user_tenant_client, "norole").status_code == 403


def test_user_role_must_belong_to_tenant(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")
    globex_role = list_roles(globex_site, globex_headers)["viewer"]

    response = acme_site.post(
        "/api/v1/admin/users",
        json={
            "username": "alice",
            "password": USER_PASSWORD,
            "display_name": "Alice",
            "role_ids": [globex_role["id"]],
        },
        headers=acme_headers,
    )
    assert response.status_code == 422

    assert acme_site.get("/api/v1/admin/users", headers=acme_headers).json()["total"] == 1


def test_user_login_failures_and_disable(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    role = list_roles(site, headers)["viewer"]
    user = create_user(site, headers, username="alice", role_id=role["id"])

    wrong = _login_user(user_tenant_client, "alice", "Wrong-password-123")
    assert wrong.status_code == 401

    disabled = site.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert disabled.status_code == 200
    blocked = _login_user(user_tenant_client, "alice")
    assert blocked.status_code == 403


def test_role_change_invalidates_existing_session(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    login = _login_user(user_tenant_client, "alice")
    assert login.status_code == 200, login.text
    access_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    acme_user = user_tenant_client("acme")
    assert acme_user.get("/api/v1/user/me", headers=access_headers).status_code == 200

    changed = site.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"role_ids": [roles["admin"]["id"]]},
        headers=headers,
    )
    assert changed.status_code == 200

    stale = acme_user.get("/api/v1/user/me", headers=access_headers)
    assert stale.status_code == 401

    relogin = _login_user(user_tenant_client, "alice")
    assert relogin.status_code == 200
    new_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    profile = acme_user.get("/api/v1/user/me", headers=new_headers).json()
    assert profile["role_code"] == "admin"


def test_refresh_rotation_replay_and_logout(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    role = list_roles(site, headers)["viewer"]
    create_user(site, headers, username="alice", role_id=role["id"])

    login = _login_user(user_tenant_client, "alice")
    assert login.status_code == 200, login.text
    tokens = login.json()
    acme_user = user_tenant_client("acme")

    rotated = acme_user.post(
        "/api/v1/user/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert rotated.status_code == 200, rotated.text

    replay = acme_user.post(
        "/api/v1/user/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401

    # 重放会撤销整个会话族，新访问令牌随之失效
    rotated_headers = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
    assert acme_user.get("/api/v1/user/me", headers=rotated_headers).status_code == 401

    fresh_login = _login_user(user_tenant_client, "alice")
    fresh_headers = {"Authorization": f"Bearer {fresh_login.json()['access_token']}"}
    assert acme_user.get("/api/v1/user/me", headers=fresh_headers).status_code == 200

    logout = acme_user.post("/api/v1/user/auth/logout", headers=fresh_headers)
    assert logout.status_code == 204
    assert acme_user.get("/api/v1/user/me", headers=fresh_headers).status_code == 401


def test_password_reset_invalidates_session(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    role = list_roles(site, headers)["viewer"]
    user = create_user(site, headers, username="alice", role_id=role["id"])

    login = _login_user(user_tenant_client, "alice")
    old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    acme_user = user_tenant_client("acme")
    assert acme_user.get("/api/v1/user/me", headers=old_headers).status_code == 200

    reset = site.post(
        f"/api/v1/admin/users/{user['id']}/password",
        json={"new_password": "New-password-123"},
        headers=headers,
    )
    assert reset.status_code == 204
    assert acme_user.get("/api/v1/user/me", headers=old_headers).status_code == 401

    assert _login_user(user_tenant_client, "alice", "New-password-123").status_code == 200
    assert _login_user(user_tenant_client, "alice").status_code == 401


def test_user_options_returns_active_users(client: TestClient, auth_headers, tenant_client) -> None:
    """下拉选项接口：只返回启用用户，字段精简，且不放宽分页上限。"""
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(
        site, headers, username="alice", role_id=roles["viewer"]["id"], display_name="Alice"
    )
    create_user(
        site,
        headers,
        username="bob",
        role_id=roles["viewer"]["id"],
        display_name="Bob",
        is_active=False,
    )

    # 分页接口仍然拒绝超过 100 的 page_size
    bad_page = site.get(
        "/api/v1/admin/users", params={"page": 1, "page_size": 500}, headers=headers
    )
    assert bad_page.status_code == 422

    options = site.get("/api/v1/admin/users/options", headers=headers)
    assert options.status_code == 200, options.text
    body = options.json()
    usernames = {item["username"] for item in body}
    # 超管 acme-admin 启用、alice 启用；bob 已禁用不出现
    assert "alice" in usernames
    assert "bob" not in usernames
    assert "acme-admin" in usernames
    # 字段精简：不应返回 tenant_id / role_id / created_at 等
    assert body, "至少应返回超管账号"
    sample = body[0]
    assert set(sample.keys()) == {"id", "username", "display_name", "is_active"}

    # 关键字过滤
    filtered = site.get("/api/v1/admin/users/options", params={"keyword": "alice"}, headers=headers)
    assert filtered.status_code == 200
    filtered_usernames = {item["username"] for item in filtered.json()}
    assert filtered_usernames == {"alice"}
