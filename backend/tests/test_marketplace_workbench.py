"""市场/运营工作台新接口端到端冒烟：市场详情、运营待审核队列、运营仪表盘。"""

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client


def _login_platform(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_listed_app(client: TestClient, headers: dict[str, str], name: str) -> str:
    created = client.post(
        "/api/v1/admin/apps", json={"name": name, "description": "测试应用"}, headers=headers
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["application_id"]

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "1",
                "data": {"nodeMeta": {"title": "开始"}},
                "config": {"inputs": [{"name": "q", "type": "string"}]},
            },
            {
                "id": "n2",
                "type": "2",
                "data": {"nodeMeta": {"title": "结束"}},
            },
        ],
        "edges": [{"sourceNodeID": "n1", "targetNodeID": "n2"}],
    }
    saved = client.put(
        f"/api/v1/admin/apps/{app_id}/graph",
        json={"graph": graph, "changelog": "init"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    listed = client.post(
        f"/api/v1/admin/apps/{app_id}/listing",
        json={"listed": True},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    return app_id


def test_marketplace_detail_and_ops_dashboard(
    client: TestClient,
    tenant_client,
) -> None:
    platform_headers = _login_platform(client)

    app_id = _create_listed_app(client, platform_headers, "冒烟测试应用")

    # 1. 市场列表（cursor 分页）
    listed = client.get("/api/v1/admin/marketplace/applications", headers=platform_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert "items" in body and "next_cursor" in body
    assert any(item["id"] == app_id for item in body["items"])

    # 2. 创建租户并以租户身份查市场详情
    create_tenant(client, platform_headers, code="smoke", name="冒烟公司")
    site, tenant_headers, _ = tenant_admin_client(tenant_client, "smoke")

    detail = site.get(f"/api/v1/admin/marketplace/applications/{app_id}", headers=tenant_headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["application"]["id"] == app_id
    assert detail_body["my_subscription"] is None
    assert detail_body["my_latest_apply"] is None
    assert detail_body["inputs"][0]["name"] == "q"

    # 3. 租户提交一条申请单
    submitted = site.post(
        "/api/v1/admin/applies",
        json={
            "application_id": app_id,
            "apply_type": "TRIAL",
            "expect_text": "想试用",
            "contact": "smoke@example.com",
        },
        headers=tenant_headers,
    )
    assert submitted.status_code == 201, submitted.text

    # 4. 运营待审核队列应包含该申请
    pending = client.get("/api/v1/admin/applies/ops/pending", headers=platform_headers)
    assert pending.status_code == 200, pending.text
    assert any(item["application_id"] == app_id for item in pending.json())

    # 5. 运营仪表盘统计非空
    dashboard = client.get("/api/v1/admin/applies/ops/dashboard", headers=platform_headers)
    assert dashboard.status_code == 200, dashboard.text
    stats = dashboard.json()
    assert stats["pending_count"] >= 1
    assert "active_grants" in stats
