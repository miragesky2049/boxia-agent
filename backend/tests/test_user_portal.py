"""用户端门户：登录限制、智能体可见性、资源过滤与启停控制。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    USER_PASSWORD,
    create_agent,
    create_tenant,
    create_user,
    grant_resource,
    list_roles,
    tenant_admin_client,
)


def _login(site: TestClient, username: str, password: str = USER_PASSWORD):
    return site.post(
        "/api/v1/user/auth/login",
        json={"username": username, "password": password},
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_login_requires_tenant_subdomain(client: TestClient, user_client) -> None:
    response = user_client.post(
        "/api/v1/user/auth/login",
        json={"username": "alice", "password": USER_PASSWORD},
    )
    assert response.status_code == 403


def test_tenant_owned_agent_visible_by_default(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    agent = create_agent(site, headers, "租户智能体")
    skill = site.post(
        "/api/v1/admin/skills",
        json={"name": "租户技能", "description": "", "content": "", "config": {}, "agent_id": agent["id"]},
        headers=headers,
    )
    assert skill.status_code == 201, skill.text

    user_site = user_tenant_client("acme")
    login = _login(user_site, "alice")
    assert login.status_code == 200, login.text
    user_headers = _headers(login.json()["access_token"])

    listed = user_site.get("/api/v1/user/agents", headers=user_headers)
    assert [item["id"] for item in listed.json()["items"]] == [agent["id"]]

    detail = user_site.get(f"/api/v1/user/agents/{agent['id']}", headers=user_headers)
    assert detail.status_code == 200
    assert [item["id"] for item in detail.json()["skills"]] == [skill.json()["id"]]


def test_disabled_agent_and_resource_hidden_from_user(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    agent = create_agent(site, headers, "租户智能体")
    skill = site.post(
        "/api/v1/admin/skills",
        json={"name": "租户技能", "description": "", "content": "", "config": {}, "agent_id": agent["id"]},
        headers=headers,
    ).json()
    disabled_skill = site.post(
        "/api/v1/admin/skills",
        json={
            "name": "停用技能",
            "description": "",
            "content": "",
            "config": {},
            "agent_id": agent["id"],
            "is_enabled": False,
        },
        headers=headers,
    )
    assert disabled_skill.status_code == 201

    user_site = user_tenant_client("acme")
    login = _login(user_site, "alice")
    user_headers = _headers(login.json()["access_token"])

    detail = user_site.get(f"/api/v1/user/agents/{agent['id']}", headers=user_headers)
    assert [item["id"] for item in detail.json()["skills"]] == [skill["id"]]

    disabled_agent = site.put(
        f"/api/v1/admin/agents/{agent['id']}",
        json={
            "name": "租户智能体",
            "avatar_url": "",
            "description": "",
            "is_enabled": False,
            "config": {},
            "tool_ids": [],
            "skill_ids": [],
        },
        headers=headers,
    )
    assert disabled_agent.status_code == 200

    assert user_site.get("/api/v1/user/agents", headers=user_headers).json()["total"] == 0
    assert (
        user_site.get(f"/api/v1/user/agents/{agent['id']}", headers=user_headers).status_code
        == 404
    )

    # 恢复启用后再次可见
    enabled_agent = site.put(
        f"/api/v1/admin/agents/{agent['id']}",
        json={
            "name": "租户智能体",
            "avatar_url": "",
            "description": "",
            "is_enabled": True,
            "config": {},
            "tool_ids": [],
            "skill_ids": [],
        },
        headers=headers,
    )
    assert enabled_agent.status_code == 200
    assert user_site.get("/api/v1/user/agents", headers=user_headers).json()["total"] == 1


def test_platform_resource_direct_grant_overrides_agent_inheritance(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="viewer-user", role_id=roles["viewer"]["id"])
    create_user(site, headers, username="admin-user", role_id=roles["admin"]["id"])

    agent = create_agent(client, auth_headers, "平台智能体")
    skill = client.post(
        "/api/v1/admin/skills",
        json={
            "name": "平台技能",
            "description": "",
            "content": "",
            "config": {},
            "agent_id": agent["id"],
        },
        headers=auth_headers,
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )
    grant_resource(
        client,
        auth_headers,
        resource_type="skill",
        resource_id=skill_id,
        grants=[{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}],
    )

    user_site = user_tenant_client("acme")
    viewer_headers = _headers(_login(user_site, "viewer-user").json()["access_token"])
    admin_headers = _headers(_login(user_site, "admin-user").json()["access_token"])

    viewer_detail = user_site.get(
        f"/api/v1/user/agents/{agent['id']}", headers=viewer_headers
    )
    admin_detail = user_site.get(
        f"/api/v1/user/agents/{agent['id']}", headers=admin_headers
    )
    assert viewer_detail.status_code == 200
    assert [item["id"] for item in viewer_detail.json()["skills"]] == [skill_id]
    assert admin_detail.status_code == 200
    assert admin_detail.json()["skills"] == []
