"""资源归属与克隆：agent_id 校验、技能包复制、授权复制与跨租户限制。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    create_agent,
    create_tenant,
    grant_resource,
    list_roles,
    tenant_admin_client,
)


def _skill(
    site: TestClient,
    headers: dict[str, str],
    name: str,
    agent_id: int | None = None,
    content: str = "",
):
    payload: dict = {"name": name, "description": "", "content": content, "config": {}}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return site.post("/api/v1/admin/skills", json=payload, headers=headers)


def test_clone_skill_to_agent_copies_files_and_grants(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    source_agent = create_agent(site, headers, "源智能体")
    target_agent = create_agent(site, headers, "目标智能体")
    skill = _skill(site, headers, "源技能", source_agent["id"], content="入口内容")
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    written = site.put(
        f"/api/v1/admin/skills/{skill_id}/files",
        json={"path": "references/a.md", "content": "资料"},
        headers=headers,
    )
    assert written.status_code == 200, written.text

    grant_resource(
        site,
        headers,
        resource_type="skill",
        resource_id=skill_id,
        grants=[{"tenant_id": tenant["id"], "role_id": roles["viewer"]["id"]}],
    )

    cloned = site.post(
        f"/api/v1/admin/skills/{skill_id}/clone",
        json={"agent_id": target_agent["id"], "name": "目标技能"},
        headers=headers,
    )
    assert cloned.status_code == 201, cloned.text
    clone = cloned.json()
    assert clone["agent_id"] == target_agent["id"]
    assert clone["tenant_id"] == tenant["id"]

    files = site.get(f"/api/v1/admin/skills/{clone['id']}/files", headers=headers)
    assert [item["path"] for item in files.json()["items"]] == ["SKILL.md", "references/a.md"]

    # 同租户克隆复制角色授权
    grants = site.get(
        "/api/v1/admin/grants",
        params={"resource_type": "skill", "resource_id": clone["id"]},
        headers=headers,
    )
    assert [(item["tenant_id"], item["role_id"]) for item in grants.json()] == [
        (tenant["id"], roles["viewer"]["id"])
    ]

    # 副本独立：修改副本不影响源技能
    site.put(
        f"/api/v1/admin/skills/{clone['id']}/files",
        json={"path": "references/a.md", "content": "副本资料"},
        headers=headers,
    )
    source_content = site.get(
        f"/api/v1/admin/skills/{skill_id}/files/content",
        params={"path": "references/a.md"},
        headers=headers,
    )
    assert source_content.json()["content"] == "资料"


def test_resource_agent_must_be_in_same_tenant(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    globex_agent = create_agent(globex_site, globex_headers, "Globex 智能体")

    rejected = _skill(acme_site, acme_headers, "越权技能", globex_agent["id"])
    assert rejected.status_code == 422

    platform_agent = create_agent(client, auth_headers, "平台智能体")
    platform_rejected = _skill(acme_site, acme_headers, "平台技能", platform_agent["id"])
    assert platform_rejected.status_code == 422


def test_clone_to_other_tenant_agent_rejected(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    acme_agent = create_agent(acme_site, acme_headers, "Acme 智能体")
    skill = _skill(acme_site, acme_headers, "Acme 技能", acme_agent["id"]).json()
    globex_agent = create_agent(globex_site, globex_headers, "Globex 智能体")

    response = acme_site.post(
        f"/api/v1/admin/skills/{skill['id']}/clone",
        json={"agent_id": globex_agent["id"], "name": "越权副本"},
        headers=acme_headers,
    )
    assert response.status_code == 404


def test_clone_platform_skill_to_tenant_agent_keeps_files(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    platform_skill = client.post(
        "/api/v1/admin/skills",
        json={"name": "平台技能", "description": "", "content": "", "config": {}},
        headers=auth_headers,
    ).json()
    client.put(
        f"/api/v1/admin/skills/{platform_skill['id']}/files",
        json={"path": "notes.md", "content": "平台资料"},
        headers=auth_headers,
    )
    grant_resource(
        client,
        auth_headers,
        resource_type="skill",
        resource_id=platform_skill["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )

    agent = create_agent(site, headers, "租户智能体")
    cloned = site.post(
        f"/api/v1/admin/skills/{platform_skill['id']}/clone",
        json={"agent_id": agent["id"], "name": "租户副本"},
        headers=headers,
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["tenant_id"] == tenant["id"]
    assert cloned.json()["agent_id"] == agent["id"]

    content = site.get(
        f"/api/v1/admin/skills/{cloned.json()['id']}/files/content",
        params={"path": "notes.md"},
        headers=headers,
    )
    assert content.json()["content"] == "平台资料"
