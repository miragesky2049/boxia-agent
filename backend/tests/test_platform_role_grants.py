"""平台角色授权：平台账号可见性、写权限与租户隔离。"""

from uuid import UUID

from fastapi.testclient import TestClient

from internal.domain.constants import PLATFORM_TENANT_ID
from tests.helpers import (
    USER_PASSWORD,
    create_agent,
    create_tenant,
    create_user,
    grant_resource,
    list_roles,
    tenant_admin_client,
)

ROLES_URL = "/api/v1/admin/roles"
ACCOUNTS_URL = "/api/v1/admin/admin-users"
OPERATOR_PASSWORD = "Operator-pass-123"


def _roles_by_code(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    response = client.get(ROLES_URL, headers=headers)
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def _create_platform_account(
    client: TestClient,
    headers: dict[str, str],
    username: str,
    role_id: UUID,
) -> dict[str, str]:
    created = client.post(
        ACCOUNTS_URL,
        json={
            "username": username,
            "password": OPERATOR_PASSWORD,
            "display_name": username,
            "role_id": role_id,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": OPERATOR_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _set_permissions(
    client: TestClient,
    headers: dict[str, str],
    role_id: UUID,
    codes: list[str],
) -> None:
    response = client.put(
        f"{ROLES_URL}/{role_id}/permissions",
        json={"codes": codes},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _agent_ids(client: TestClient, headers: dict[str, str]) -> set[str]:
    response = client.get("/api/v1/admin/agents", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


def _grant(
    client: TestClient, headers: dict[str, str], role_id: UUID, ids: list[UUID]
) -> None:
    response = client.post(
        f"{ROLES_URL}/{role_id}/grants/agent",
        json={"resource_ids": ids},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_platform_role_grant_controls_visibility(
    client: TestClient, auth_headers
) -> None:
    roles = _roles_by_code(client, auth_headers)
    admin_role_id = roles["admin"]["id"]
    operator_headers = _create_platform_account(
        client, auth_headers, "platform-ops", admin_role_id
    )

    granted_agent = create_agent(client, auth_headers, "已授权平台智能体")
    hidden_agent = create_agent(client, auth_headers, "未授权平台智能体")

    # 未授权时平台管理员看不到任何平台资源
    assert _agent_ids(client, operator_headers) == set()
    assert (
        client.get(f"/api/v1/admin/agents/{granted_agent['id']}", headers=operator_headers)
        .status_code
        == 404
    )

    _grant(client, auth_headers, admin_role_id, [granted_agent["id"]])

    assert _agent_ids(client, operator_headers) == {granted_agent["id"]}
    assert (
        client.get(f"/api/v1/admin/agents/{granted_agent['id']}", headers=operator_headers)
        .status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/admin/agents/{hidden_agent['id']}", headers=operator_headers)
        .status_code
        == 404
    )

    # 超级管理员默认全量可见
    assert _agent_ids(client, auth_headers) == {granted_agent["id"], hidden_agent["id"]}


def test_copy_platform_role_copies_grants(client: TestClient, auth_headers) -> None:
    source = client.post(
        ROLES_URL,
        json={"code": "ops", "name": "平台运营"},
        headers=auth_headers,
    )
    assert source.status_code == 201, source.text
    source_role = source.json()
    agent = create_agent(client, auth_headers, "平台运营智能体")
    _grant(client, auth_headers, source_role["id"], [agent["id"]])

    copied = client.post(
        f"{ROLES_URL}/{source_role['id']}/copy",
        json={"code": "ops-copy", "name": "平台运营副本"},
        headers=auth_headers,
    )
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    assert copy["tenant_id"] == str(PLATFORM_TENANT_ID)
    assert copy["is_system"] is False

    summary = client.get(f"{ROLES_URL}/{copy['id']}/grants/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["agent"] == 1

    grants = client.get(
        f"{ROLES_URL}/{copy['id']}/grants",
        params={"resource_type": "agent", "granted_only": True, "page_size": 100},
        headers=auth_headers,
    )
    assert grants.status_code == 200, grants.text
    assert [item["resource_id"] for item in grants.json()["items"]] == [agent["id"]]


def test_platform_viewer_is_read_only(client: TestClient, auth_headers) -> None:
    roles = _roles_by_code(client, auth_headers)
    viewer_role_id = roles["viewer"]["id"]
    viewer_headers = _create_platform_account(
        client, auth_headers, "platform-viewer-grants", viewer_role_id
    )
    agent = create_agent(client, auth_headers, "只读平台智能体")
    _grant(client, auth_headers, viewer_role_id, [agent["id"]])

    assert client.get("/api/v1/admin/agents", headers=viewer_headers).status_code == 200
    denied = client.post(
        "/api/v1/admin/agents",
        json={
            "name": "只读写入",
            "avatar_url": "",
            "description": "",
            "is_enabled": True,
            "config": {},
            "tool_ids": [],
            "skill_ids": [],
        },
        headers=viewer_headers,
    )
    assert denied.status_code == 403


def test_platform_superadmin_role_is_not_writable(
    client: TestClient, auth_headers
) -> None:
    roles = _roles_by_code(client, auth_headers)
    superadmin_role_id = roles["superadmin"]["id"]
    agent = create_agent(client, auth_headers, "超管平台智能体")

    summary = client.get(
        f"{ROLES_URL}/{superadmin_role_id}/grants/summary", headers=auth_headers
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["agent"] == 1

    added = client.post(
        f"{ROLES_URL}/{superadmin_role_id}/grants/agent",
        json={"resource_ids": [agent["id"]]},
        headers=auth_headers,
    )
    assert added.status_code == 422

    replaced = client.put(
        f"{ROLES_URL}/{superadmin_role_id}/grants/agent",
        json={"resource_ids": [agent["id"]]},
        headers=auth_headers,
    )
    assert replaced.status_code == 422

    removed = client.delete(
        f"{ROLES_URL}/{superadmin_role_id}/grants/agent/{agent['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 422


def test_custom_platform_role_grant_takes_effect(
    client: TestClient, auth_headers
) -> None:
    custom = client.post(
        ROLES_URL,
        json={"code": "auditor", "name": "平台审计"},
        headers=auth_headers,
    )
    assert custom.status_code == 201, custom.text
    custom_role_id = custom.json()["id"]
    # 新建平台角色无任何权限，先授予管理端入口与技能查看权限才能登录并读取
    _set_permissions(
        client,
        auth_headers,
        custom_role_id,
        ["system:console:access", "skill:read"],
    )

    account_headers = _create_platform_account(
        client, auth_headers, "platform-auditor", custom_role_id
    )
    skill = client.post(
        "/api/v1/admin/skills",
        json={"name": "平台审计技能", "description": "", "content": "", "config": {}},
        headers=auth_headers,
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    assert client.get("/api/v1/admin/skills", headers=account_headers).json()["total"] == 0

    granted = client.post(
        f"{ROLES_URL}/{custom_role_id}/grants/skill",
        json={"resource_ids": [skill_id]},
        headers=auth_headers,
    )
    assert granted.status_code == 200, granted.text

    listed = client.get("/api/v1/admin/skills", headers=account_headers).json()
    assert [item["id"] for item in listed["items"]] == [skill_id]

    # 授权候选只包含平台级资源
    candidates = client.get(
        f"{ROLES_URL}/{custom_role_id}/grants",
        params={"resource_type": "skill", "granted_only": "false"},
        headers=auth_headers,
    )
    assert candidates.status_code == 200, candidates.text
    assert [item["resource_id"] for item in candidates.json()["items"]] == [skill_id]


def test_platform_role_grants_do_not_affect_tenant_roles(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, tenant_headers, _ = tenant_admin_client(tenant_client, "acme")
    tenant_roles = list_roles(site, tenant_headers)

    roles = _roles_by_code(client, auth_headers)
    agent = create_agent(client, auth_headers, "平台共享智能体")

    # 只授权给平台角色，租户侧不可见
    _grant(client, auth_headers, roles["admin"]["id"], [agent["id"]])
    assert site.get("/api/v1/admin/agents", headers=tenant_headers).json()["total"] == 0

    # 下发给租户后，租户用户才可见
    create_user(site, tenant_headers, username="acme-user", role_id=tenant_roles["viewer"]["id"])
    grant_resource(
        client,
        auth_headers,
        resource_type="agent",
        resource_id=agent["id"],
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )

    user_site = user_tenant_client("acme")
    login = user_site.post(
        "/api/v1/user/auth/login",
        json={"username": "acme-user", "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    listed = user_site.get("/api/v1/user/agents", headers=user_headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [agent["id"]]
