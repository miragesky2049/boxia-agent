"""智能体 user 端可见范围：all/custom 模式、部门子树、指定人员、全量替换。"""

from uuid import UUID

from fastapi.testclient import TestClient

from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

AGENTS_URL = "/api/v1/admin/agents"
DEPTS_URL = "/api/v1/admin/departments"
EMP_URL = "/api/v1/admin/employments"


def _grant_to_viewer_role(
    site: TestClient,
    headers: dict[str, str],
    *,
    tenant_id: str,
    resource_id: UUID,
    viewer_role_id: str,
) -> None:
    """把租户智能体授权给当前租户的 viewer 角色，让所有 viewer 用户可见。"""
    response = site.put(
        "/api/v1/admin/grants",
        params={"resource_type": "agent", "resource_id": resource_id},
        json={"grants": [{"tenant_id": tenant_id, "role_id": viewer_role_id}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _agent_payload(name: str, department_id: str) -> dict:
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


def _create_dept(site: TestClient, headers: dict[str, str], name: str, parent_id=None) -> dict:
    response = site.post(
        DEPTS_URL, json={"name": name, "parent_id": parent_id}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_agent(site: TestClient, headers: dict[str, str], name: str, dept_id: str) -> dict:
    response = site.post(AGENTS_URL, json=_agent_payload(name, dept_id), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _assign_employment(
    site: TestClient, headers: dict[str, str], user_id: str, department_id: str
) -> None:
    response = site.post(
        EMP_URL,
        json={
            "user_id": user_id,
            "department_id": department_id,
            "position": "员工",
            "started_at": "2026-01-01",
        },
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text


def _user_headers(user_tenant_client, username: str) -> tuple[TestClient, dict[str, str]]:
    site = user_tenant_client("acme")
    response = site.post(
        "/api/v1/user/auth/login",
        json={"username": username, "password": USER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return site, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _visible_user_ids(site: TestClient, headers: dict[str, str]) -> set[str]:
    response = site.get("/api/v1/user/agents", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


def test_default_visibility_all_makes_agent_visible_to_all_users(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    """默认 all 模式：任何 user 端用户（无任职）都能看到已授权智能体。"""
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    dept = _create_dept(site, headers, "研发部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    agent = _create_agent(site, headers, "全员助手", dept["id"])
    # 智能体默认 visibility_mode=all
    detail = site.get(f"{AGENTS_URL}/{agent['id']}", headers=headers).json()
    assert detail["visibility_mode"] == "all"

    _grant_to_viewer_role(
        site, headers,
        tenant_id=tenant["id"],
        resource_id=agent["id"],
        viewer_role_id=roles["viewer"]["id"],
    )

    user_site, user_headers = _user_headers(user_tenant_client, "alice")
    assert agent["id"] in _visible_user_ids(user_site, user_headers)


def test_custom_department_with_subtree_filters_user_visibility(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    """custom + 含子树部门：子部门用户可见、其他部门用户不可见。"""
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    parent = _create_dept(site, headers, "研发中心")
    child = _create_dept(site, headers, "前端组", parent["id"])
    other = _create_dept(site, headers, "市场部")

    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    bob = create_user(site, headers, username="bob", role_id=roles["viewer"]["id"])
    _assign_employment(site, headers, alice["id"], child["id"])
    _assign_employment(site, headers, bob["id"], other["id"])

    agent = _create_agent(site, headers, "研发助手", parent["id"])
    _grant_to_viewer_role(
        site, headers,
        tenant_id=tenant["id"],
        resource_id=agent["id"],
        viewer_role_id=roles["viewer"]["id"],
    )

    # 切到 custom，只授权父部门（含子树）
    save_resp = site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [{"department_id": parent["id"], "include_subtree": True}],
            "user_ids": [],
        },
        headers=headers,
    )
    assert save_resp.status_code == 200, save_resp.text
    assert save_resp.json()["mode"] == "custom"
    assert save_resp.json()["departments"][0]["include_subtree"] is True

    alice_site, alice_headers = _user_headers(user_tenant_client, "alice")
    bob_site, bob_headers = _user_headers(user_tenant_client, "bob")
    # alice 在子部门，命中父部门含子树
    assert agent["id"] in _visible_user_ids(alice_site, alice_headers)
    # bob 在市场部，未命中
    assert agent["id"] not in _visible_user_ids(bob_site, bob_headers)


def test_custom_department_without_subtree_only_matches_direct_department(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    """custom + 不含子树部门：仅直接挂在该部门的用户可见。"""
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    parent = _create_dept(site, headers, "研发中心")
    child = _create_dept(site, headers, "前端组", parent["id"])

    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    bob = create_user(site, headers, username="bob", role_id=roles["viewer"]["id"])
    _assign_employment(site, headers, alice["id"], child["id"])
    _assign_employment(site, headers, bob["id"], parent["id"])

    agent = _create_agent(site, headers, "直挂助手", parent["id"])
    _grant_to_viewer_role(
        site, headers,
        tenant_id=tenant["id"],
        resource_id=agent["id"],
        viewer_role_id=roles["viewer"]["id"],
    )

    site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [{"department_id": parent["id"], "include_subtree": False}],
            "user_ids": [],
        },
        headers=headers,
    )

    alice_site, alice_headers = _user_headers(user_tenant_client, "alice")
    bob_site, bob_headers = _user_headers(user_tenant_client, "bob")
    # bob 直接挂在 parent，可见
    assert agent["id"] in _visible_user_ids(bob_site, bob_headers)
    # alice 在子部门，不含子树时不可见
    assert agent["id"] not in _visible_user_ids(alice_site, alice_headers)


def test_custom_user_directly_granted_sees_agent_without_department(
    client: TestClient, auth_headers, tenant_client, user_tenant_client
) -> None:
    """custom + 指定用户：被指定 user_id 直接命中，即使无当前任职。"""
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    dept = _create_dept(site, headers, "研发部")

    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    bob = create_user(site, headers, username="bob", role_id=roles["viewer"]["id"])
    # 不给 alice 安排任职

    agent = _create_agent(site, headers, "指定助手", dept["id"])
    _grant_to_viewer_role(
        site, headers,
        tenant_id=tenant["id"],
        resource_id=agent["id"],
        viewer_role_id=roles["viewer"]["id"],
    )

    site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [],
            "user_ids": [alice["id"]],
        },
        headers=headers,
    )

    alice_site, alice_headers = _user_headers(user_tenant_client, "alice")
    bob_site, bob_headers = _user_headers(user_tenant_client, "bob")
    # alice 被直接指定，可见（即使无任职）
    assert agent["id"] in _visible_user_ids(alice_site, alice_headers)
    # bob 未被指定，不可见
    assert agent["id"] not in _visible_user_ids(bob_site, bob_headers)


def test_visibility_put_is_full_replace(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """PUT /visibility 全量替换：旧部门/人员关联被清除。"""
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    dept_a = _create_dept(site, headers, "A 部")
    dept_b = _create_dept(site, headers, "B 部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    agent = _create_agent(site, headers, "替换助手", dept_a["id"])

    site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [{"department_id": dept_a["id"], "include_subtree": True}],
            "user_ids": [alice["id"]],
        },
        headers=headers,
    )

    # 第二次 PUT 只保留 B 部，alice 与 A 部都被清除
    site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [{"department_id": dept_b["id"], "include_subtree": False}],
            "user_ids": [],
        },
        headers=headers,
    )

    got = site.get(f"{AGENTS_URL}/{agent['id']}/visibility", headers=headers).json()
    assert got["mode"] == "custom"
    assert got["departments"] == [
        {"department_id": dept_b["id"], "include_subtree": False}
    ]
    assert got["user_ids"] == []


def test_admin_list_not_affected_by_user_visibility(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """管理端列表不受 user 端可见范围影响：管理员仍能看到全部租户智能体。"""
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    dept = _create_dept(site, headers, "研发部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    agent = _create_agent(site, headers, "管理员视角助手", dept["id"])
    site.put(
        f"{AGENTS_URL}/{agent['id']}/visibility",
        json={
            "mode": "custom",
            "departments": [],
            "user_ids": [alice["id"]],
        },
        headers=headers,
    )

    listed = site.get(AGENTS_URL, headers=headers).json()
    ids = {item["id"] for item in listed["items"]}
    assert agent["id"] in ids
