"""租户角色管理：初始化、CRUD、系统角色保护与租户隔离。"""

from fastapi.testclient import TestClient

from internal.domain.constants import PLATFORM_TENANT_ID
from tests.helpers import (
    TENANT_ADMIN_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)


def test_tenant_roles_initialized_and_custom_crud(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    roles = list_roles(site, headers)
    assert {"superadmin", "admin", "viewer"} <= set(roles)
    assert all(item["is_system"] for item in roles.values())

    created = site.post(
        "/api/v1/admin/roles",
        json={
            "code": "sales",
            "name": "销售",
            "description": "销售角色",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["is_system"] is False
    assert role["is_active"] is True

    duplicate = site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售二部"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    updated = site.patch(
        f"/api/v1/admin/roles/{role['id']}",
        json={"name": "销售一组", "description": "调整后"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "销售一组"

    deleted = site.delete(f"/api/v1/admin/roles/{role['id']}", headers=headers)
    assert deleted.status_code == 204
    assert "sales" not in list_roles(site, headers)


def test_system_role_cannot_be_disabled_or_deleted(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    viewer = list_roles(site, headers)["viewer"]

    disabled = site.patch(
        f"/api/v1/admin/roles/{viewer['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert disabled.status_code == 422

    deleted = site.delete(f"/api/v1/admin/roles/{viewer['id']}", headers=headers)
    assert deleted.status_code == 422


def test_referenced_role_cannot_be_deleted(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    custom = site.post(
        "/api/v1/admin/roles",
        json={"code": "support", "name": "客服"},
        headers=headers,
    ).json()
    create_user(site, headers, role_id=custom["id"])

    deleted = site.delete(f"/api/v1/admin/roles/{custom['id']}", headers=headers)
    assert deleted.status_code == 409


def test_copy_role_copies_grants(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    role = site.post(
        "/api/v1/admin/roles",
        json={
            "code": "sales",
            "name": "销售",
            "description": "销售角色",
        },
        headers=headers,
    ).json()
    skill = site.post(
        "/api/v1/admin/skills",
        json={"name": "销售技能", "description": "", "content": "", "config": {}},
        headers=headers,
    ).json()
    granted = site.post(
        f"/api/v1/admin/roles/{role['id']}/grants/skill",
        json={"resource_ids": [skill["id"]]},
        headers=headers,
    )
    assert granted.status_code == 200, granted.text

    copied = site.post(
        f"/api/v1/admin/roles/{role['id']}/copy",
        json={"code": "sales-copy", "name": "销售副本"},
        headers=headers,
    )
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    assert copy["is_system"] is False
    assert copy["is_active"] is True
    assert copy["description"] == "销售角色"

    summary = site.get(
        f"/api/v1/admin/roles/{copy['id']}/grants/summary", headers=headers
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["skill"] == 1

    grants = site.get(
        f"/api/v1/admin/roles/{copy['id']}/grants",
        params={"resource_type": "skill", "granted_only": True, "page_size": 100},
        headers=headers,
    )
    assert grants.status_code == 200, grants.text
    assert [item["resource_id"] for item in grants.json()["items"]] == [skill["id"]]

    duplicate = site.post(
        f"/api/v1/admin/roles/{role['id']}/copy",
        json={"code": "sales-copy", "name": "销售副本二"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    superadmin_id = list_roles(site, headers)["superadmin"]["id"]
    forbidden = site.post(
        f"/api/v1/admin/roles/{superadmin_id}/copy",
        json={"code": "superadmin-copy", "name": "超管副本"},
        headers=headers,
    )
    assert forbidden.status_code == 422


def test_create_role_has_no_permissions_and_copy_inherits_permissions(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    created = site.post(
        "/api/v1/admin/roles",
        json={"code": "audit", "name": "审计"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    # 新建角色不预置任何功能权限，由授权接口显式维护
    permissions = site.get(f"/api/v1/admin/roles/{role_id}/permissions", headers=headers)
    assert permissions.status_code == 200, permissions.text
    assert permissions.json()["codes"] == []

    # 基础权限字段已移除，编辑接口不再接收
    rejected = site.patch(
        f"/api/v1/admin/roles/{role_id}",
        json={"system_role": "superadmin"},
        headers=headers,
    )
    assert rejected.status_code == 422

    admin_id = list_roles(site, headers)["admin"]["id"]
    admin_codes = set(
        site.get(f"/api/v1/admin/roles/{admin_id}/permissions", headers=headers).json()["codes"]
    )
    copied = site.post(
        f"/api/v1/admin/roles/{admin_id}/copy",
        json={"code": "ops-admin", "name": "运营管理员"},
        headers=headers,
    )
    assert copied.status_code == 201, copied.text
    copied_codes = set(
        site.get(
            f"/api/v1/admin/roles/{copied.json()['id']}/permissions", headers=headers
        ).json()["codes"]
    )
    assert copied_codes == admin_codes
    assert "skill:read" in copied_codes


def test_copy_role_is_tenant_isolated(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    acme_role = acme_site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售"},
        headers=acme_headers,
    ).json()
    denied = globex_site.post(
        f"/api/v1/admin/roles/{acme_role['id']}/copy",
        json={"code": "sales-copy", "name": "销售副本"},
        headers=globex_headers,
    )
    assert denied.status_code == 404


def test_platform_manages_own_roles_only(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)

    created = client.post(
        "/api/v1/admin/roles",
        json={"code": "ops", "name": "平台运营"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] == str(PLATFORM_TENANT_ID)
    # 产品级入口创建的角色统一标记为系统角色
    assert created.json()["is_system"] is True

    listed = client.get("/api/v1/admin/roles", headers=auth_headers)
    assert listed.status_code == 200
    codes = {item["code"] for item in listed.json()}
    assert {"superadmin", "admin", "viewer", "ops"} <= codes
    assert all(item["tenant_id"] == str(PLATFORM_TENANT_ID) for item in listed.json())

    tenant = client.get("/api/v1/admin/tenants", headers=auth_headers).json()
    tenant_item = next(item for item in tenant["items"] if item["code"] == "acme")
    forbidden = client.get(
        "/api/v1/admin/roles",
        params={"tenant_id": tenant_item["id"]},
        headers=auth_headers,
    )
    assert forbidden.status_code == 403


def test_roles_are_tenant_isolated(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    globex = create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    acme_site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售"},
        headers=acme_headers,
    )
    assert "sales" in list_roles(acme_site, acme_headers)
    assert "sales" not in list_roles(globex_site, globex_headers)

    forbidden = acme_site.get(
        "/api/v1/admin/roles",
        params={"tenant_id": globex["id"]},
        headers=acme_headers,
    )
    assert forbidden.status_code == 403


def test_viewer_admin_cannot_access_role_management(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    viewer = list_roles(site, headers)["viewer"]

    created_user = site.post(
        "/api/v1/admin/users",
        json={
            "username": "acme-viewer-admin",
            "password": TENANT_ADMIN_PASSWORD,
            "display_name": "只读管理员",
            "role_ids": [viewer["id"]],
        },
        headers=headers,
    )
    assert created_user.status_code == 201, created_user.text

    login = site.post(
        "/api/v1/admin/auth/login",
        json={"username": "acme-viewer-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 只读角色仅拥有资源查看权限，不含角色管理页面权限
    assert site.get("/api/v1/admin/roles", headers=viewer_headers).status_code == 403
    denied = site.post(
        "/api/v1/admin/roles",
        json={"code": "sales", "name": "销售"},
        headers=viewer_headers,
    )
    assert denied.status_code == 403
