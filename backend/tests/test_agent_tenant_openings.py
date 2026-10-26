"""产品智能体对租户的开通/关闭：开通独立于角色授权，并兼容旧授权接口。"""

from uuid import UUID

from fastapi.testclient import TestClient

from tests.helpers import (
    USER_PASSWORD,
    create_agent,
    create_tenant,
    grant_resource,
    list_roles,
    tenant_admin_client,
)


def _create_admin_with_role(
    site: TestClient, headers: dict[str, str], username: str, role_id: UUID
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


def _tenant_agents(
    client: TestClient, headers: dict[str, str], tenant_id: UUID, **params
) -> dict:
    response = client.get(
        f"/api/v1/admin/tenants/{tenant_id}/agents",
        params={"page": 1, "page_size": 20, **params},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_opened(
    client: TestClient, headers: dict[str, str], tenant_id: UUID, agent_id: UUID, opened: bool
) -> dict:
    response = client.put(
        f"/api/v1/admin/tenants/{tenant_id}/agents/{agent_id}",
        json={"opened": opened},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _batch_set_opened(
    client: TestClient,
    headers: dict[str, str],
    tenant_id: UUID,
    agent_ids: list[UUID],
    opened: bool,
) -> dict:
    response = client.post(
        f"/api/v1/admin/tenants/{tenant_id}/agents/batch",
        json={"agent_ids": agent_ids, "opened": opened},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _agent_tenants(client: TestClient, headers: dict[str, str], agent_id: UUID) -> dict:
    response = client.get(f"/api/v1/admin/agents/{agent_id}/tenants", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_open_close_agent_for_tenant(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    agent = create_agent(client, auth_headers, "产品智能体")

    listed = _tenant_agents(client, auth_headers, tenant["id"])
    assert listed["total"] == 1
    assert listed["items"][0]["is_opened"] is False
    assert listed["items"][0]["opened_at"] is None

    # 未开通时租户超管也看不到产品智能体
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 0

    opened = _set_opened(client, auth_headers, tenant["id"], agent["id"], True)
    assert opened["is_opened"] is True
    assert opened["opened_at"] is not None

    assert _tenant_agents(client, auth_headers, tenant["id"], opened_only=True)["total"] == 1
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 1

    opened_tenants = _agent_tenants(client, auth_headers, agent["id"])
    assert opened_tenants["total"] == 1
    assert opened_tenants["items"][0]["code"] == tenant["code"]

    closed = _set_opened(client, auth_headers, tenant["id"], agent["id"], False)
    assert closed["is_opened"] is False
    assert closed["opened_at"] is None

    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 0
    assert _agent_tenants(client, auth_headers, agent["id"])["total"] == 0


def test_open_alone_does_not_grant_roles(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    admin_headers = _create_admin_with_role(
        site, headers, "plain-admin", roles["admin"]["id"]
    )
    agent = create_agent(client, auth_headers, "产品智能体")

    _set_opened(client, auth_headers, tenant["id"], agent["id"], True)

    # 开通只是租户级可用；超管全量可见，普通角色仍需数据授权
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 1
    assert site.get("/api/v1/admin/agents", headers=admin_headers).json()["total"] == 0

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": roles["admin"]["id"]}],
    )
    assert site.get("/api/v1/admin/agents", headers=admin_headers).json()["total"] == 1


def test_close_clears_tenant_role_grants(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    admin_headers = _create_admin_with_role(
        site, headers, "plain-admin", roles["admin"]["id"]
    )
    agent = create_agent(client, auth_headers, "产品智能体")

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": roles["admin"]["id"]}],
    )
    assert site.get("/api/v1/admin/agents", headers=admin_headers).json()["total"] == 1

    _set_opened(client, auth_headers, tenant["id"], agent["id"], False)

    grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": agent["id"],
            "tenant_id": tenant["id"],
        },
        headers=auth_headers,
    ).json()
    assert grants == []

    # 重新开通后历史授权不会复活
    _set_opened(client, auth_headers, tenant["id"], agent["id"], True)
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 1
    assert site.get("/api/v1/admin/agents", headers=admin_headers).json()["total"] == 0


def test_batch_open_and_close_agents(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    first = create_agent(client, auth_headers, "产品智能体A")
    second = create_agent(client, auth_headers, "产品智能体B")
    agent_ids = [first["id"], second["id"]]

    opened = _batch_set_opened(client, auth_headers, tenant["id"], agent_ids, True)
    assert opened["opened"] is True
    assert opened["count"] == 2
    assert set(opened["agent_ids"]) == set(agent_ids)
    assert _tenant_agents(client, auth_headers, tenant["id"], opened_only=True)["total"] == 2
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 2

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=first["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": roles["admin"]["id"]}],
    )

    closed = _batch_set_opened(client, auth_headers, tenant["id"], agent_ids, False)
    assert closed["opened"] is False
    assert closed["count"] == 2
    assert _tenant_agents(client, auth_headers, tenant["id"], opened_only=True)["total"] == 0
    assert site.get("/api/v1/admin/agents", headers=headers).json()["total"] == 0

    grants = client.get(
        "/api/v1/admin/grants",
        params={
            "resource_type": "agent",
            "resource_id": first["id"],
            "tenant_id": tenant["id"],
        },
        headers=auth_headers,
    ).json()
    assert grants == []


def test_batch_open_rejects_unknown_agent_and_tenant_scope(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    agent = create_agent(client, auth_headers, "产品智能体")

    response = client.post(
        f"/api/v1/admin/tenants/{tenant['id']}/agents/batch",
        json={"agent_ids": [agent["id"], "0190f5a0-0000-7000-8000-000000000000"], "opened": True},
        headers=auth_headers,
    )
    assert response.status_code == 404
    # 批量操作要么全部成功，要么全部不生效
    assert _tenant_agents(client, auth_headers, tenant["id"], opened_only=True)["total"] == 0

    forbidden = site.post(
        f"/api/v1/admin/tenants/{tenant['id']}/agents/batch",
        json={"agent_ids": [agent["id"]], "opened": True},
        headers=headers,
    )
    assert forbidden.status_code == 403


def test_platform_grant_keeps_openings_in_sync(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    agent = create_agent(client, auth_headers, "产品智能体")

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )
    assert _tenant_agents(client, auth_headers, tenant["id"])["items"][0]["is_opened"] is True
    assert _agent_tenants(client, auth_headers, agent["id"])["total"] == 1

    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[],
    )
    assert _tenant_agents(client, auth_headers, tenant["id"])["items"][0]["is_opened"] is False
    assert _agent_tenants(client, auth_headers, agent["id"])["total"] == 0


def test_openings_scope_and_not_found(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    agent = create_agent(client, auth_headers, "产品智能体")

    # 开通接口仅产品级平台可用
    assert (
        site.get(f"/api/v1/admin/tenants/{tenant['id']}/agents", headers=headers).status_code
        == 403
    )
    assert (
        site.put(
            f"/api/v1/admin/tenants/{tenant['id']}/agents/{agent['id']}",
            json={"opened": True},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        site.get(f"/api/v1/admin/agents/{agent['id']}/tenants", headers=headers).status_code
        == 403
    )

    assert (
        client.get("/api/v1/admin/tenants/0190f5a0-0000-7000-8000-000000000000/agents", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/admin/tenants/{tenant['id']}/agents/0190f5a0-0000-7000-8000-000000000000",
            json={"opened": True},
            headers=auth_headers,
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/admin/agents/0190f5a0-0000-7000-8000-000000000000/tenants", headers=auth_headers).status_code
        == 404
    )
