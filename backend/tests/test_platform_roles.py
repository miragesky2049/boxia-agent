"""平台自有角色：CRUD、系统角色保护、账号引用与作用域隔离。"""

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client

ROLES_URL = "/api/v1/admin/roles"
PLATFORM_ADMIN_PASSWORD = "Platform-pass-123"


def _platform_roles(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    response = client.get(ROLES_URL, headers=headers)
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def test_platform_roles_initialized_and_created_role_is_system(
    client: TestClient, auth_headers
) -> None:
    roles = _platform_roles(client, auth_headers)
    assert {"superadmin", "admin", "viewer"} <= set(roles)
    assert all(item["tenant_id"] is None for item in roles.values())
    assert all(item["is_system"] for item in roles.values())

    created = client.post(
        ROLES_URL,
        json={"code": "ops", "name": "平台运营", "description": ""},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["tenant_id"] is None
    # 产品级入口创建的角色统一标记为系统角色
    assert role["is_system"] is True

    duplicate_code = client.post(
        ROLES_URL,
        json={"code": "ops", "name": "平台运营二部"},
        headers=auth_headers,
    )
    assert duplicate_code.status_code == 409

    duplicate_name = client.post(
        ROLES_URL,
        json={"code": "ops2", "name": "平台运营"},
        headers=auth_headers,
    )
    assert duplicate_name.status_code == 409

    updated = client.patch(
        f"{ROLES_URL}/{role['id']}",
        json={"name": "平台运营组"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "平台运营组"

    # 基础权限字段已移除，编辑接口不再接收
    changed = client.patch(
        f"{ROLES_URL}/{role['id']}",
        json={"system_role": "admin"},
        headers=auth_headers,
    )
    assert changed.status_code == 422

    # 系统角色不可删除
    deleted = client.delete(f"{ROLES_URL}/{role['id']}", headers=auth_headers)
    assert deleted.status_code == 422
    assert "ops" in _platform_roles(client, auth_headers)


def test_platform_system_roles_are_protected(
    client: TestClient, auth_headers
) -> None:
    roles = _platform_roles(client, auth_headers)
    viewer = roles["viewer"]
    superadmin = roles["superadmin"]

    disabled = client.patch(
        f"{ROLES_URL}/{viewer['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert disabled.status_code == 422

    deleted = client.delete(f"{ROLES_URL}/{viewer['id']}", headers=auth_headers)
    assert deleted.status_code == 422

    changed = client.patch(
        f"{ROLES_URL}/{superadmin['id']}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert changed.status_code == 422


def test_platform_role_bound_to_account_cannot_delete(
    client: TestClient, auth_headers
) -> None:
    custom = client.post(
        ROLES_URL,
        json={"code": "support", "name": "平台客服"},
        headers=auth_headers,
    ).json()
    granted = client.put(
        f"{ROLES_URL}/{custom['id']}/permissions",
        json={"codes": ["system:console:access"]},
        headers=auth_headers,
    )
    assert granted.status_code == 200, granted.text
    created = client.post(
        "/api/v1/admin/admin-users",
        json={
            "username": "platform-support",
            "password": PLATFORM_ADMIN_PASSWORD,
            "display_name": "平台客服",
            "role_id": custom["id"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["role_id"] == custom["id"]

    # 平台角色均为系统角色，即使未被引用也不可删除
    deleted = client.delete(f"{ROLES_URL}/{custom['id']}", headers=auth_headers)
    assert deleted.status_code == 422
    assert "support" in _platform_roles(client, auth_headers)


def test_platform_and_tenant_roles_are_isolated(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, tenant_headers, _ = tenant_admin_client(tenant_client, "acme")

    site.post(
        ROLES_URL,
        json={"code": "sales", "name": "销售"},
        headers=tenant_headers,
    )
    client.post(
        ROLES_URL,
        json={"code": "ops", "name": "平台运营"},
        headers=auth_headers,
    )

    platform_codes = set(_platform_roles(client, auth_headers))
    assert "sales" not in platform_codes
    assert "ops" in platform_codes

    tenant_codes = {
        item["code"]
        for item in site.get(ROLES_URL, headers=tenant_headers).json()
    }
    assert "ops" not in tenant_codes
    assert "sales" in tenant_codes
