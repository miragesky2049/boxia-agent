"""P1-7 OPS 直开应用：直开 active、重复 422、未来 start_time wait_effect、租户作用域 403。"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client


def _grant_url(app_id: str) -> str:
    return f"/api/v1/admin/entitlements/applications/{app_id}/grant"


def _list_url(tenant_id: str) -> str:
    return f"/api/v1/admin/entitlements/tenants/{tenant_id}"


@pytest.fixture()
def env(client: TestClient, auth_headers: dict[str, str]) -> dict:
    """直开所需数据：租户 + 应用。"""
    tenant = create_tenant(client, auth_headers, code="opsgrant", name="直开租户")
    app_resp = client.post(
        "/api/v1/admin/apps",
        json={"name": "直开应用", "description": "P1-7"},
        headers=auth_headers,
    )
    assert app_resp.status_code == 201, app_resp.text
    return {"tenant_id": tenant["id"], "app_id": app_resp.json()["application_id"]}


def _payload(env: dict, start_time: datetime | None = None) -> dict:
    return {
        "tenant_id": env["tenant_id"],
        "auth_type": "FORMAL",
        "contract_no": "HT-001",
        "quota_json": {"qps": 10},
        "start_time": (start_time or datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "expire_time": None,
        "remark": "直开用例",
    }


def test_direct_grant_active(client: TestClient, auth_headers, env):
    """直开 → 权益列表可见 active + auth_source=OPS，quota/remark 落库。"""
    resp = client.post(_grant_url(env["app_id"]), json=_payload(env), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["instance_id"]

    listed = client.get(_list_url(env["tenant_id"]), headers=auth_headers).json()
    assert listed["total"] == 1
    row = listed["items"][0]
    assert row["object_type"] == "app"
    assert row["status"] == "active"
    assert row["auth_source"] == "OPS"
    assert row["auth_type"] == "FORMAL"
    assert row["quota"] == {"qps": 10}
    assert row["remark"] == "直开用例"


def test_duplicate_grant_rejected(client: TestClient, auth_headers, env):
    """同一租户+应用重复直开 → 422（exists_active_grant GrantError 转译）。"""
    assert (
        client.post(_grant_url(env["app_id"]), json=_payload(env), headers=auth_headers).status_code
        == 200
    )
    second = client.post(_grant_url(env["app_id"]), json=_payload(env), headers=auth_headers)
    assert second.status_code == 422
    assert "ACTIVE" in second.json()["detail"]


def test_future_start_time_wait_effect(client: TestClient, auth_headers, env):
    """未来 start_time → 读侧有效状态 wait_effect。"""
    resp = client.post(
        _grant_url(env["app_id"]),
        json=_payload(env, start_time=datetime.now(UTC) + timedelta(days=1)),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = client.get(_list_url(env["tenant_id"]), headers=auth_headers).json()["items"][0]
    assert row["status"] == "wait_effect"


def test_tenant_scope_rejected(client: TestClient, auth_headers, tenant_client, env):
    """租户子域名访问直开入口 → 403（require_platform_admin）。"""
    site, headers, _ = tenant_admin_client(tenant_client, "opsgrant")
    resp = site.post(_grant_url(env["app_id"]), json=_payload(env), headers=headers)
    assert resp.status_code == 403
