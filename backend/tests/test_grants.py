"""资源授权：按租户、按角色、资源继承与跨作用域限制。"""

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


def _skill_payload(name: str, agent_id: int | None = None) -> dict:
    payload: dict = {"name": name, "description": "", "content": "", "config": {}}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


def _user_headers(user_tenant_client, username: str) -> dict[str, str]:
    site = user_tenant_client("acme")
    response = site.post(
        "/api/v1/user/auth/login",
        json={"username": username, "password": USER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_admin_with_role(
    site: TestClient, headers: dict[str, str], username: str, role_id: int
) -> dict[str, str]:
    created = site.post(
        "/api/v1/admin/users",
        json={
            "username": username,
            "password": USER_PASSWORD,
            "display_name": username,
            "role_ids": [role_id],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    login = site.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_platform_agent_requires_tenant_grant(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    user_site = user_tenant_client("acme")
    user_headers = _user_headers(user_tenant_client, "alice")

    agent = create_agent(client, auth_headers, "平台智能体")

    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 0
    assert user_site.get("/api/v1/user/agents", headers=user_headers).json()["total"] == 0
    assert site.get(f"/api/v1/admin/agents/{agent['id']}", headers=headers).status_code == 404

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )

    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 1
    user_list = user_site.get("/api/v1/user/agents", headers=user_headers).json()
    assert [item["id"] for item in user_list["items"]] == [agent["id"]]
    assert site.get(f"/api/v1/admin/agents/{agent['id']}", headers=headers).status_code == 200


def test_agent_grant_role_filter(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="viewer-user", role_id=roles["viewer"]["id"])
    create_user(site, headers, username="admin-user", role_id=roles["admin"]["id"])
    viewer_headers = _create_admin_with_role(site, headers, "viewer-admin", roles["viewer"]["id"])
    admin_headers = _create_admin_with_role(site, headers, "admin-admin", roles["admin"]["id"])

    agent = create_agent(client, auth_headers, "只读角色智能体")
    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}],
    )

    # 租户超管不做角色过滤
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 1
    assert site.get("/api/v1/admin/agents", headers=viewer_headers).json()["total"] == 1
    assert site.get("/api/v1/admin/agents", headers=admin_headers).json()["total"] == 0
    assert site.get(f"/api/v1/admin/agents/{agent['id']}", headers=admin_headers).status_code == 404

    user_site = user_tenant_client("acme")
    viewer_user = user_site.get(
        "/api/v1/user/agents", headers=_user_headers(user_tenant_client, "viewer-user")
    )
    admin_user = user_site.get(
        "/api/v1/user/agents", headers=_user_headers(user_tenant_client, "admin-user")
    )
    assert viewer_user.json()["total"] == 1
    assert admin_user.json()["total"] == 0


def test_platform_resource_inherits_agent_grant(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    user_site = user_tenant_client("acme")
    user_headers = _user_headers(user_tenant_client, "alice")

    agent = create_agent(client, auth_headers, "平台智能体")
    skill = client.post(
        "/api/v1/admin/skills",
        json=_skill_payload("平台技能", agent_id=agent["id"]),
        headers=auth_headers,
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    # 未授权智能体前，技能也不可见
    assert skill_id not in [
        item["id"] for item in site.get("/api/v1/admin/skills", headers=headers).json()["items"]
    ]

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )

    listed = site.get("/api/v1/admin/skills", headers=headers).json()["items"]
    assert skill_id in [item["id"] for item in listed]

    detail = user_site.get(f"/api/v1/user/agents/{agent['id']}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    assert [item["id"] for item in detail.json()["skills"]] == [skill_id]

    # 撤销智能体授权后，技能继承关系同步失效
    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[],
    )
    assert (
        user_site.get(f"/api/v1/user/agents/{agent['id']}", headers=user_headers).status_code == 404
    )


def test_tenant_owned_resource_role_filter(client: TestClient, auth_headers, tenant_client) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    viewer_admin = _create_admin_with_role(site, headers, "viewer-admin", roles["viewer"]["id"])
    admin_admin = _create_admin_with_role(site, headers, "admin-admin", roles["admin"]["id"])

    skill = site.post("/api/v1/admin/skills", json=_skill_payload("租户技能"), headers=headers)
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    # 无单独授权时，本租户全部角色可见
    assert skill_id in [
        item["id"] for item in site.get("/api/v1/admin/skills", headers=admin_admin).json()["items"]
    ]

    grant_resource(
        site,
        headers,
        resource_type="skill",
        resource_id=skill_id,
        grants=[{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}],
    )

    viewer_items = site.get("/api/v1/admin/skills", headers=viewer_admin).json()["items"]
    admin_items = site.get("/api/v1/admin/skills", headers=admin_admin).json()["items"]
    assert skill_id in [item["id"] for item in viewer_items]
    assert skill_id not in [item["id"] for item in admin_items]


def test_grant_scope_restrictions(client: TestClient, auth_headers, tenant_client) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    platform_skill = client.post(
        "/api/v1/admin/skills", json=_skill_payload("平台技能"), headers=auth_headers
    ).json()
    tenant_skill = site.post(
        "/api/v1/admin/skills", json=_skill_payload("租户技能"), headers=headers
    ).json()

    tenant_grants_platform = site.put(
        "/api/v1/admin/grants",
        params={"resource_type": "skill", "resource_id": platform_skill["id"]},
        json={"grants": [{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}]},
        headers=headers,
    )
    assert tenant_grants_platform.status_code in {403, 404}

    platform_grants_tenant = client.put(
        "/api/v1/admin/grants",
        params={"resource_type": "skill", "resource_id": tenant_skill["id"]},
        json={"grants": [{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}]},
        headers=auth_headers,
    )
    assert platform_grants_tenant.status_code == 404

    unknown = client.get(
        "/api/v1/admin/grants",
        params={"resource_type": "skill", "resource_id": 999999},
        headers=auth_headers,
    )
    assert unknown.status_code == 404

    invalid_type = client.get(
        "/api/v1/admin/grants",
        params={"resource_type": "unknown", "resource_id": platform_skill["id"]},
        headers=auth_headers,
    )
    assert invalid_type.status_code == 422


def _overview(
    client: TestClient,
    headers: dict[str, str],
    resource_type: str,
    **params,
) -> dict:
    response = client.get(
        "/api/v1/admin/grants/overview",
        params={"resource_type": resource_type, "page": 1, "page_size": 20, **params},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _batch(
    client: TestClient,
    headers: dict[str, str],
    *,
    resource_type: str,
    resource_ids: list[int],
    mode: str,
    tenant_id: int | None = None,
    role_ids: list[int] | None = None,
):
    return client.put(
        "/api/v1/admin/grants/batch",
        json={
            "resource_type": resource_type,
            "resource_ids": resource_ids,
            "mode": mode,
            "tenant_id": tenant_id,
            "role_ids": role_ids or [],
        },
        headers=headers,
    )


def test_overview_platform_scope_and_summary(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant_a = create_tenant(client, auth_headers, code="acme", name="Acme")
    tenant_b = create_tenant(client, auth_headers, code="beta", name="Beta")
    agent_granted = create_agent(client, auth_headers, "已授权智能体")
    agent_plain = create_agent(client, auth_headers, "未授权智能体")

    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    tenant_agent = site.post(
        "/api/v1/admin/agents",
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
    assert tenant_agent.status_code == 201, tenant_agent.text

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent_granted["id"],
        grants=[
            {"tenant_id": tenant_a["id"], "role_id": None},
            {"tenant_id": tenant_b["id"], "role_id": None},
        ],
    )

    overview = _overview(client, auth_headers, "agent")
    by_id = {item["resource_id"]: item for item in overview["items"]}
    # 平台视角只列平台级资源，租户自有资源不出现
    assert tenant_agent.json()["id"] not in by_id
    granted = by_id[agent_granted["id"]]
    assert granted["is_platform"] is True
    assert granted["grant_count"] == 2
    assert granted["tenant_count"] == 2
    assert granted["is_default_visible"] is False
    assert by_id[agent_plain["id"]]["grant_count"] == 0

    granted_only = _overview(client, auth_headers, "agent", grant_state="granted")
    assert [item["resource_id"] for item in granted_only["items"]] == [agent_granted["id"]]
    ungranted_only = _overview(client, auth_headers, "agent", grant_state="ungranted")
    assert [item["resource_id"] for item in ungranted_only["items"]] == [agent_plain["id"]]
    searched = _overview(client, auth_headers, "agent", keyword="已授权")
    assert [item["resource_id"] for item in searched["items"]] == [agent_granted["id"]]

    paged = _overview(client, auth_headers, "agent", page_size=1)
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


def test_overview_tenant_scope_default_and_roles(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    default_skill = site.post(
        "/api/v1/admin/skills", json=_skill_payload("默认可见技能"), headers=headers
    )
    limited_skill = site.post(
        "/api/v1/admin/skills", json=_skill_payload("限定角色技能"), headers=headers
    )
    assert default_skill.status_code == 201, default_skill.text
    assert limited_skill.status_code == 201, limited_skill.text

    platform_skill = client.post(
        "/api/v1/admin/skills", json=_skill_payload("平台技能"), headers=auth_headers
    )
    assert platform_skill.status_code == 201, platform_skill.text

    grant_resource(
        site,
        headers,
        resource_type="skill",
        resource_id=limited_skill.json()["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}],
    )

    overview = _overview(site, headers, "skill")
    by_id = {item["resource_id"]: item for item in overview["items"]}
    assert platform_skill.json()["id"] not in by_id
    assert by_id[default_skill.json()["id"]]["is_default_visible"] is True
    limited = by_id[limited_skill.json()["id"]]
    assert limited["is_default_visible"] is False
    assert limited["grant_count"] == 1
    assert limited["role_count"] == 1

    ungranted = _overview(site, headers, "skill", grant_state="ungranted")
    assert [item["resource_id"] for item in ungranted["items"]] == [default_skill.json()["id"]]


def test_list_grants_tenant_isolation(client: TestClient, auth_headers, tenant_client) -> None:
    tenant_a = create_tenant(client, auth_headers, code="acme", name="Acme")
    tenant_b = create_tenant(client, auth_headers, code="beta", name="Beta")
    site_a, headers_a, _ = tenant_admin_client(tenant_client, "acme")
    roles_a = list_roles(site_a, headers_a)

    agent = create_agent(client, auth_headers, "跨租户智能体")
    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[
            {"tenant_id": tenant_a["id"], "role_id": roles_a["viewer"]["id"]},
            {"tenant_id": tenant_b["id"], "role_id": None},
        ],
    )

    scoped = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent["id"],
            "tenant_id": tenant_a["id"],
        },
        headers=auth_headers,
    )
    assert scoped.status_code == 200, scoped.text
    assert [item["tenant_id"] for item in scoped.json()] == [tenant_a["id"]]

    own = site_a.get(
        "/api/v1/admin/grants",
        params={"resource_type": "agent", "resource_id": agent["id"]},
        headers=headers_a,
    )
    assert own.status_code == 200, own.text
    assert [item["tenant_id"] for item in own.json()] == [tenant_a["id"]]

    forbidden = site_a.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent["id"],
            "tenant_id": tenant_b["id"],
        },
        headers=headers_a,
    )
    assert forbidden.status_code == 403


def test_batch_grant_modes_are_tenant_scoped(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant_a = create_tenant(client, auth_headers, code="acme", name="Acme")
    tenant_b = create_tenant(client, auth_headers, code="beta", name="Beta")
    site_a, headers_a, _ = tenant_admin_client(tenant_client, "acme")
    roles_a = list_roles(site_a, headers_a)
    viewer_id = roles_a["viewer"]["id"]
    admin_id = roles_a["admin"]["id"]

    agent_one = create_agent(client, auth_headers, "批量智能体一")
    agent_two = create_agent(client, auth_headers, "批量智能体二")
    ids = [agent_one["id"], agent_two["id"]]

    # 先给 B 租户整租户授权，后续操作 A 不得影响 B
    response = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=ids,
        mode="replace",
        tenant_id=tenant_b["id"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2

    replaced = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=ids,
        mode="replace",
        tenant_id=tenant_a["id"],
        role_ids=[viewer_id],
    )
    assert replaced.status_code == 200, replaced.text
    grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent_one["id"],
            "tenant_id": tenant_a["id"],
        },
        headers=auth_headers,
    ).json()
    assert [item["role_id"] for item in grants] == [viewer_id]

    merged = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=[agent_one["id"], agent_one["id"]],
        mode="merge",
        tenant_id=tenant_a["id"],
        role_ids=[admin_id],
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["updated"] == 1
    grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent_one["id"],
            "tenant_id": tenant_a["id"],
        },
        headers=auth_headers,
    ).json()
    assert sorted(item["role_id"] for item in grants) == sorted([viewer_id, admin_id])

    # 其他租户授权保持不变
    tenant_b_grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent_one["id"],
            "tenant_id": tenant_b["id"],
        },
        headers=auth_headers,
    ).json()
    assert len(tenant_b_grants) == 1
    assert tenant_b_grants[0]["role_id"] is None

    cleared = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=ids,
        mode="clear",
        tenant_id=tenant_a["id"],
    )
    assert cleared.status_code == 200, cleared.text
    grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent_one["id"],
            "tenant_id": tenant_a["id"],
        },
        headers=auth_headers,
    ).json()
    assert grants == []


def test_batch_grant_validation(client: TestClient, auth_headers, tenant_client) -> None:
    tenant_a = create_tenant(client, auth_headers, code="acme", name="Acme")
    tenant_b = create_tenant(client, auth_headers, code="beta", name="Beta")
    site_b, headers_b, _ = tenant_admin_client(tenant_client, "beta")
    roles_b = list_roles(site_b, headers_b)

    agent = create_agent(client, auth_headers, "校验智能体")

    missing_tenant = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=[agent["id"]],
        mode="replace",
    )
    assert missing_tenant.status_code == 422

    too_many = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=list(range(1, 102)),
        mode="replace",
        tenant_id=tenant_a["id"],
    )
    assert too_many.status_code == 422

    missing = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=[agent["id"], 999999],
        mode="replace",
        tenant_id=tenant_a["id"],
    )
    assert missing.status_code == 404
    assert (
        client.get(
            "/api/v1/admin/grants",
            params={"resource_type": "agent", "resource_id": agent["id"]},
            headers=auth_headers,
        ).json()
        == []
    )

    cross_role = _batch(
        client,
        auth_headers,
        resource_type="agent",
        resource_ids=[agent["id"]],
        mode="replace",
        tenant_id=tenant_a["id"],
        role_ids=[roles_b["viewer"]["id"]],
    )
    assert cross_role.status_code == 422

    platform_skill = client.post(
        "/api/v1/admin/skills", json=_skill_payload("平台技能"), headers=auth_headers
    ).json()
    tenant_on_platform = _batch(
        site_b,
        headers_b,
        resource_type="skill",
        resource_ids=[platform_skill["id"]],
        mode="replace",
        role_ids=[roles_b["viewer"]["id"]],
    )
    assert tenant_on_platform.status_code == 404

    cross_tenant_scope = _batch(
        site_b,
        headers_b,
        resource_type="skill",
        resource_ids=[platform_skill["id"]],
        mode="replace",
        tenant_id=tenant_b["id"],
        role_ids=[roles_b["viewer"]["id"]],
    )
    assert cross_tenant_scope.status_code in {403, 404}


def test_tenant_batch_clear_restores_default_visibility(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    skill = site.post("/api/v1/admin/skills", json=_skill_payload("租户技能"), headers=headers)
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    limited = _batch(
        site,
        headers,
        resource_type="skill",
        resource_ids=[skill_id],
        mode="replace",
        tenant_id=tenant["id"],
        role_ids=[roles["viewer"]["id"]],
    )
    assert limited.status_code == 200, limited.text
    overview = _overview(site, headers, "skill")
    assert overview["items"][0]["is_default_visible"] is False

    cleared = _batch(
        site,
        headers,
        resource_type="skill",
        resource_ids=[skill_id],
        mode="clear",
        tenant_id=tenant["id"],
    )
    assert cleared.status_code == 200, cleared.text
    overview = _overview(site, headers, "skill")
    assert overview["items"][0]["is_default_visible"] is True


def test_non_superadmin_cannot_manage_grants(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    admin_headers = _create_admin_with_role(site, headers, "plain-admin", roles["admin"]["id"])

    overview = site.get(
        "/api/v1/admin/grants/overview",
        params={"resource_type": "agent"},
        headers=admin_headers,
    )
    assert overview.status_code == 403

    batch = _batch(
        site,
        admin_headers,
        resource_type="agent",
        resource_ids=[1],
        mode="clear",
    )
    assert batch.status_code == 403


def test_admin_context_menus_include_grants(
    client: TestClient, auth_headers, tenant_client
) -> None:
    platform_context = client.get("/api/v1/admin/context", headers=auth_headers)
    assert platform_context.status_code == 200, platform_context.text
    assert "grants" in platform_context.json()["menus"]

    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    tenant_context = site.get("/api/v1/admin/context", headers=headers)
    assert tenant_context.status_code == 200, tenant_context.text
    menus = tenant_context.json()["menus"]
    assert "grants" in menus
    assert "tenants" not in menus
