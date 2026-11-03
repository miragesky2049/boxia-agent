"""P1-6 /admin/entitlements API：列表/反查/预览/批量与权限门禁（租户 403、缺 button 403、超限 422）。"""

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client

BASE = "/api/v1/admin/entitlements"
_ROLE_PASSWORD = "Entitlement-pass-123"
_PURGE_PASSWORD = "EntPurge-pass-123"


@pytest.fixture()
def env(client: TestClient, auth_headers: dict[str, str]) -> dict:
    """平台作用域数据：租户 + 应用 + skill 资源。"""
    tenant = create_tenant(client, auth_headers, code="entapi", name="权益接口租户")
    app_resp = client.post(
        "/api/v1/admin/apps",
        json={"name": "权益接口应用", "description": "P1-6"},
        headers=auth_headers,
    )
    assert app_resp.status_code == 201, app_resp.text
    skill_resp = client.post(
        "/api/v1/admin/resources",
        json={
            "type": "skill",
            "name": "权益接口技能",
            "config": {"url": "https://example.com/api", "method": "GET"},
        },
        headers=auth_headers,
    )
    assert skill_resp.status_code == 201, skill_resp.text
    return {
        "tenant_id": tenant["id"],
        "app_id": app_resp.json()["application_id"],
        "skill_id": skill_resp.json()["resource_id"],
    }


def _items(env: dict) -> list[dict]:
    return [
        {"object_type": "app", "object_id": env["app_id"]},
        {"object_type": "skill", "object_id": env["skill_id"]},
    ]


def test_preview_grant_list_revoke_flow(client: TestClient, auth_headers, env):
    """预览→批量开通→列表/反查→软失效→持久状态过滤的闭环。"""
    assert (
        client.get(f"{BASE}/tenants/{env['tenant_id']}", headers=auth_headers).json()["total"] == 0
    )

    preview = client.post(
        f"{BASE}/preview",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": _items(env)},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert len(body["add"]) == 2 and body["remove"] == [] and body["unchanged"] == []

    applied = client.post(
        f"{BASE}/batch",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": _items(env)},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"updated": 2, "failed": [], "affected_role_grants": 0}

    listed = client.get(f"{BASE}/tenants/{env['tenant_id']}", headers=auth_headers).json()
    assert listed["total"] == 2
    assert all(
        item["status"] == "active" and item["auth_source"] == "OPS" for item in listed["items"]
    )

    after = client.post(
        f"{BASE}/preview",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": _items(env)},
        headers=auth_headers,
    ).json()
    assert len(after["unchanged"]) == 2 and after["add"] == []

    reverse = client.get(
        f"{BASE}/objects/skill/{env['skill_id']}/tenants", headers=auth_headers
    ).json()
    assert reverse["total"] == 1
    assert reverse["items"][0]["tenant_id"] == env["tenant_id"]
    assert reverse["items"][0]["status"] == "active"

    revoked = client.post(
        f"{BASE}/batch",
        json={
            "tenant_id": env["tenant_id"],
            "mode": "revoke",
            "items": [{"object_type": "skill", "object_id": env["skill_id"]}],
            "reason": "接口用例取消",
        },
        headers=auth_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"updated": 1, "failed": [], "affected_role_grants": 0}

    filtered = client.get(
        f"{BASE}/tenants/{env['tenant_id']}?status=revoked", headers=auth_headers
    ).json()
    assert [item["object_type"] for item in filtered["items"]] == ["skill"]
    assert filtered["items"][0]["remark"] == "接口用例取消"


def test_grant_deprecated_and_missing_object_reported_in_failed(
    client: TestClient, auth_headers, env
):
    """弃用对象与不存在对象：batch 返回 failed 明细且整体不写入。"""
    dep_resp = client.post(
        "/api/v1/admin/resources",
        json={
            "type": "skill",
            "name": "弃用技能",
            "config": {"url": "https://example.com/api", "method": "GET"},
        },
        headers=auth_headers,
    ).json()
    patched = client.patch(
        f"/api/v1/admin/resources/{dep_resp['resource_id']}",
        json={"is_deprecated": True},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    result = client.post(
        f"{BASE}/batch",
        json={
            "tenant_id": env["tenant_id"],
            "mode": "grant",
            "items": [
                {"object_type": "skill", "object_id": dep_resp["resource_id"]},
                {"object_type": "skill", "object_id": str(uuid.uuid4())},
            ],
        },
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["updated"] == 0
    reasons = {item["reason"] for item in body["failed"]}
    assert any("弃用" in r for r in reasons) and any("不存在" in r for r in reasons)
    assert (
        client.get(f"{BASE}/tenants/{env['tenant_id']}", headers=auth_headers).json()["total"] == 0
    )


def test_tenant_scope_rejected(client: TestClient, auth_headers, tenant_client, env):
    """租户子域名访问权益入口 → 403（require_platform_admin）。"""
    site, headers, _ = tenant_admin_client(tenant_client, "entapi")
    resp = site.get(f"{BASE}/tenants/{env['tenant_id']}", headers=headers)
    assert resp.status_code == 403


def test_button_permission_required(client: TestClient, auth_headers, env):
    """仅有 page:entitlements 的账号可读列表，写 batch 403。"""
    role = client.post(
        "/api/v1/admin/roles", json={"code": "ent-viewer", "name": "权益只读"}, headers=auth_headers
    ).json()
    granted = client.put(
        f"/api/v1/admin/roles/{role['id']}/permissions",
        json={"codes": ["system:console:access", "page:entitlements"]},
        headers=auth_headers,
    )
    assert granted.status_code == 200, granted.text
    created = client.post(
        "/api/v1/admin/admin-users",
        json={
            "username": "ent-viewer",
            "password": _ROLE_PASSWORD,
            "display_name": "权益只读账号",
            "role_id": role["id"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "ent-viewer", "password": _ROLE_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get(f"{BASE}/tenants/{env['tenant_id']}", headers=headers).status_code == 200
    blocked = client.post(
        f"{BASE}/batch",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": _items(env)},
        headers=headers,
    )
    assert blocked.status_code == 403


def test_items_count_bounds(client: TestClient, auth_headers, env):
    """items 上限 100：0 项或 101 项均 422。"""
    empty = client.post(
        f"{BASE}/batch",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": []},
        headers=auth_headers,
    )
    assert empty.status_code == 422
    many = [{"object_type": "skill", "object_id": str(uuid.uuid4())} for _ in range(101)]
    over = client.post(
        f"{BASE}/batch",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": many},
        headers=auth_headers,
    )
    assert over.status_code == 422


def test_purge_requires_confirm_and_deletes_row(client: TestClient, auth_headers, env):
    """P3-6：purge 未确认 422；superadmin 确认后物理删行并返回 audit_id。"""
    granted = client.post(
        f"{BASE}/batch",
        json={"tenant_id": env["tenant_id"], "mode": "grant", "items": _items(env)},
        headers=auth_headers,
    )
    assert granted.status_code == 200 and granted.json()["updated"] == 2

    unconfirmed = client.post(
        f"{BASE}/purge",
        json={
            "tenant_id": env["tenant_id"],
            "object_type": "skill",
            "object_id": env["skill_id"],
            "confirm": False,
        },
        headers=auth_headers,
    )
    assert unconfirmed.status_code == 422

    purged = client.post(
        f"{BASE}/purge",
        json={
            "tenant_id": env["tenant_id"],
            "object_type": "skill",
            "object_id": env["skill_id"],
            "confirm": True,
            "reason": "接口用例清理",
        },
        headers=auth_headers,
    )
    assert purged.status_code == 200, purged.text
    body = purged.json()
    assert body["deleted"] == 1 and body["role_grants_deleted"] == 0
    uuid.UUID(body["audit_id"])

    listed = client.get(f"{BASE}/tenants/{env['tenant_id']}", headers=auth_headers).json()
    assert [item["object_type"] for item in listed["items"]] == ["app"]


def test_purge_forbidden_for_non_superadmin(client: TestClient, auth_headers, env):
    """有 button:entitlement:manage 的非 superadmin 角色：batch 可写，purge 仍 403。"""
    role = client.post(
        "/api/v1/admin/roles", json={"code": "ent-ops", "name": "权益运营"}, headers=auth_headers
    ).json()
    granted = client.put(
        f"/api/v1/admin/roles/{role['id']}/permissions",
        json={
            "codes": [
                "system:console:access",
                "page:entitlements",
                "button:entitlement:manage",
            ]
        },
        headers=auth_headers,
    )
    assert granted.status_code == 200, granted.text
    client.post(
        "/api/v1/admin/admin-users",
        json={
            "username": "ent-ops",
            "password": _PURGE_PASSWORD,
            "display_name": "权益运营账号",
            "role_id": role["id"],
        },
        headers=auth_headers,
    )
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "ent-ops", "password": _PURGE_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    batch = client.post(
        f"{BASE}/batch",
        json={
            "tenant_id": env["tenant_id"],
            "mode": "grant",
            "items": [{"object_type": "skill", "object_id": env["skill_id"]}],
        },
        headers=headers,
    )
    assert batch.status_code == 200, batch.text

    blocked = client.post(
        f"{BASE}/purge",
        json={
            "tenant_id": env["tenant_id"],
            "object_type": "skill",
            "object_id": env["skill_id"],
            "confirm": True,
        },
        headers=headers,
    )
    assert blocked.status_code == 403
