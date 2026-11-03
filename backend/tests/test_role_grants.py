"""角色详情页授权：有效授权、写保护、候选门槛与跨租户隔离。"""

from uuid import UUID

from fastapi.testclient import TestClient

from internal.domain.entity.access import RESOURCE_TYPES as _RESOURCE_TYPES
from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    grant_resource,
    list_roles,
    tenant_admin_client,
)

_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


def _create_tenant_tool(
    client: TestClient,
    headers: dict[str, str],
    tenant_id: UUID,
    name: str,
) -> dict:
    """平台管理员创建归属于指定租户的工具（resource 表）。"""
    response = client.post(
        "/api/v1/admin/resources",
        json={
            "type": "tool",
            "name": name,
            "config": _TOOL_CONFIG,
            "owner_type": "tenant",
            "owner_id": str(tenant_id),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {"id": response.json()["resource_id"], "name": name}


def _create_platform_tool(
    client: TestClient, headers: dict[str, str], name: str
) -> dict:
    """平台管理员创建产品级工具（resource 表）。"""
    response = client.post(
        "/api/v1/admin/resources",
        json={"type": "tool", "name": name, "config": _TOOL_CONFIG},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {"id": response.json()["resource_id"], "name": name}


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


def _summary(site: TestClient, headers: dict[str, str], role_id: UUID) -> dict[str, int]:
    response = site.get(
        f"/api/v1/admin/roles/{role_id}/grants/summary", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["counts"]


def _grant_items(
    site: TestClient,
    headers: dict[str, str],
    role_id: UUID,
    resource_type: str,
    granted_only: bool = True,
) -> list[dict]:
    response = site.get(
        f"/api/v1/admin/roles/{role_id}/grants",
        params={
            "resource_type": resource_type,
            "granted_only": granted_only,
            "page": 1,
            "page_size": 100,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_role_detail_and_grant_lifecycle(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    viewer_id = roles["viewer"]["id"]

    detail = site.get(f"/api/v1/admin/roles/{viewer_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["code"] == "viewer"

    # 平台不能查看租户角色：不带 tenant_id 视为不存在，带 tenant_id 直接拒绝
    assert client.get(f"/api/v1/admin/roles/{viewer_id}", headers=auth_headers).status_code == 404
    platform_detail = client.get(
        f"/api/v1/admin/roles/{viewer_id}",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert platform_detail.status_code == 403

    skill = _create_tenant_tool(client, auth_headers, tenant["id"], "角色授权技能")
    skill_id = skill["id"]
    assert _summary(site, headers, viewer_id) == {item: 0 for item in _RESOURCE_TYPES}

    added = site.post(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": [skill_id]},
        headers=headers,
    )
    assert added.status_code == 200, added.text
    assert added.json()["updated"] == 1
    assert _summary(site, headers, viewer_id)["tool"] == 1

    granted = _grant_items(site, headers, viewer_id, "tool")
    assert [item["resource_id"] for item in granted] == [skill_id]
    assert granted[0]["is_granted"] is True
    assert granted[0]["is_platform"] is False

    candidates = _grant_items(site, headers, viewer_id, "tool", granted_only=False)
    assert [item["resource_id"] for item in candidates] == [skill_id]
    assert candidates[0]["is_granted"] is True

    # 重复追加不重复写入
    again = site.post(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": [skill_id]},
        headers=headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["updated"] == 0

    removed = site.delete(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool/{skill_id}",
        headers=headers,
    )
    assert removed.status_code == 204, removed.text
    assert _summary(site, headers, viewer_id)["tool"] == 0
    assert _grant_items(site, headers, viewer_id, "tool") == []

    # 整体替换可一次授权多个资源，空数组表示清空
    second = _create_tenant_tool(client, auth_headers, tenant["id"], "第二个技能")
    replaced = site.put(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": [skill_id, second["id"]]},
        headers=headers,
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["updated"] == 2
    assert _summary(site, headers, viewer_id)["tool"] == 2

    cleared = site.put(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": []},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["updated"] == 0
    assert _summary(site, headers, viewer_id)["tool"] == 0


def test_superadmin_role_grants_read_only(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    superadmin_id = roles["superadmin"]["id"]
    skill = _create_tenant_tool(client, auth_headers, tenant["id"], "超管技能")

    assert _summary(site, headers, superadmin_id)["tool"] == 1

    added = site.post(
        f"/api/v1/admin/roles/{superadmin_id}/grants/tool",
        json={"resource_ids": [skill["id"]]},
        headers=headers,
    )
    assert added.status_code == 422

    replaced = site.put(
        f"/api/v1/admin/roles/{superadmin_id}/grants/tool",
        json={"resource_ids": [skill["id"]]},
        headers=headers,
    )
    assert replaced.status_code == 422

    removed = site.delete(
        f"/api/v1/admin/roles/{superadmin_id}/grants/tool/{skill['id']}",
        headers=headers,
    )
    assert removed.status_code == 422


def test_role_grants_require_tenant_superadmin(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    viewer_id = roles["viewer"]["id"]
    admin_headers = _create_admin_with_role(site, headers, "plain-admin", roles["admin"]["id"])

    assert (
        site.get(
            f"/api/v1/admin/roles/{viewer_id}/grants/summary", headers=admin_headers
        ).status_code
        == 403
    )
    assert (
        site.get(
            f"/api/v1/admin/roles/{viewer_id}/grants",
            params={"resource_type": "tool"},
            headers=admin_headers,
        ).status_code
        == 403
    )


def test_role_grants_platform_resource_candidate_gate(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)
    viewer_id = roles["viewer"]["id"]
    admin_id = roles["admin"]["id"]

    platform_skill_id = _create_platform_tool(client, auth_headers, "平台技能")["id"]

    # 未下发本租户的平台资源不可出现在候选集，也不能被授权
    candidates = _grant_items(site, headers, viewer_id, "tool", granted_only=False)
    assert platform_skill_id not in {item["resource_id"] for item in candidates}
    rejected = site.post(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": [platform_skill_id]},
        headers=headers,
    )
    assert rejected.status_code == 404

    grant_resource(
        client,
        auth_headers,
        resource_type="tool",
        resource_id=platform_skill_id,
        grants=[{"tenant_id": tenant["id"], "role_id": None}],
    )

    # 整租户授权计入有效授权，并出现在候选集
    assert platform_skill_id in {
        item["resource_id"]
        for item in _grant_items(site, headers, viewer_id, "tool", granted_only=False)
    }
    assert _summary(site, headers, viewer_id)["tool"] == 1
    granted = _grant_items(site, headers, viewer_id, "tool")
    assert granted[0]["resource_id"] == platform_skill_id
    assert granted[0]["is_platform"] is True

    # 已整租户授权的资源无需重复写入
    skipped = site.post(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool",
        json={"resource_ids": [platform_skill_id]},
        headers=headers,
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["updated"] == 0

    # 取消单个角色时把整租户授权拆成其余角色的显式授权
    removed = site.delete(
        f"/api/v1/admin/roles/{viewer_id}/grants/tool/{platform_skill_id}",
        headers=headers,
    )
    assert removed.status_code == 204, removed.text
    assert _summary(site, headers, viewer_id)["tool"] == 0
    assert _summary(site, headers, admin_id)["tool"] == 1


def test_role_grants_cross_tenant_isolation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    tenant_a = create_tenant(client, auth_headers, code="acme", name="Acme")
    tenant_b = create_tenant(client, auth_headers, code="beta", name="Beta")
    site_a, headers_a, _ = tenant_admin_client(tenant_client, "acme")
    roles_a = list_roles(site_a, headers_a)
    viewer_a_id = roles_a["viewer"]["id"]

    site_b, headers_b, _ = tenant_admin_client(tenant_client, "beta")
    skill_b = _create_tenant_tool(client, auth_headers, tenant_b["id"], "Beta 技能")

    assert (
        site_b.get(f"/api/v1/admin/roles/{viewer_a_id}", headers=headers_b).status_code
        == 404
    )
    assert (
        site_b.get(
            f"/api/v1/admin/roles/{viewer_a_id}/grants/summary", headers=headers_b
        ).status_code
        == 404
    )
    assert (
        site_b.post(
            f"/api/v1/admin/roles/{viewer_a_id}/grants/tool",
            json={"resource_ids": [skill_b["id"]]},
            headers=headers_b,
        ).status_code
        == 404
    )

    skill_a = _create_tenant_tool(client, auth_headers, tenant_a["id"], "Acme 技能")
    assert (
        site_b.post(
            f"/api/v1/admin/roles/{viewer_a_id}/grants/tool",
            json={"resource_ids": [skill_a["id"]]},
            headers=headers_b,
        ).status_code
        == 404
    )

    platform_detail = client.get(
        f"/api/v1/admin/roles/{viewer_a_id}",
        params={"tenant_id": tenant_a["id"]},
        headers=auth_headers,
    )
    assert platform_detail.status_code == 403

