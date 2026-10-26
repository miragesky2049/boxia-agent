"""智能体所属部门：挂接校验、平台智能体禁挂部门、跨租户引用拒绝。"""

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client

AGENTS_URL = "/api/v1/admin/agents"
DEPTS_URL = "/api/v1/admin/departments"


def _agent_payload(name: str, department_id: str | None = None) -> dict:
    return {
        "name": name,
        "avatar_url": "",
        "description": "",
        "is_enabled": True,
        "config": {},
        "tool_ids": [],
        "skill_ids": [],
        "department_id": department_id,
    }


def _create_dept(site: TestClient, headers: dict[str, str], name: str) -> dict:
    response = site.post(DEPTS_URL, json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_agent_bind_and_clear_department(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    department = _create_dept(site, headers, "客服部")

    created = site.post(
        AGENTS_URL, json=_agent_payload("客服助手", department["id"]), headers=headers
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    assert created.json()["department_id"] == department["id"]

    detail = site.get(f"{AGENTS_URL}/{agent_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["department_id"] == department["id"]

    listed = site.get(AGENTS_URL, headers=headers).json()
    assert listed["items"][0]["department_id"] == department["id"]

    cleared = site.put(
        f"{AGENTS_URL}/{agent_id}", json=_agent_payload("客服助手", None), headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["department_id"] is None


def test_agent_department_validation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    department = _create_dept(site, headers, "停用部")

    missing = site.post(
        AGENTS_URL,
        json=_agent_payload("孤儿助手", "00000000-0000-0000-0000-000000000000"),
        headers=headers,
    )
    assert missing.status_code == 422

    assert site.post(
        f"{DEPTS_URL}/{department['id']}/status",
        json={"is_active": False},
        headers=headers,
    ).status_code == 200
    disabled = site.post(
        AGENTS_URL, json=_agent_payload("停用部助手", department["id"]), headers=headers
    )
    assert disabled.status_code == 422


def test_platform_agent_cannot_have_department(
    client: TestClient, auth_headers
) -> None:
    response = client.post(
        AGENTS_URL,
        json=_agent_payload("平台助手", "00000000-0000-0000-0000-000000000000"),
        headers=auth_headers,
    )
    assert response.status_code == 422

    created = client.post(
        AGENTS_URL, json=_agent_payload("平台助手"), headers=auth_headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["department_id"] is None
    assert created.json()["is_platform"] is True


def test_agent_department_cross_tenant_rejected(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")
    globex_dept = _create_dept(globex_site, globex_headers, "Globex 部门")

    response = acme_site.post(
        AGENTS_URL,
        json=_agent_payload("越权助手", globex_dept["id"]),
        headers=acme_headers,
    )
    assert response.status_code == 422
