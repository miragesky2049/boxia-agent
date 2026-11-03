"""市场开通校验：sale_mode 门槛、上架/启用前置、失效实例运行 403。"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.database import get_engine
from tests.helpers import create_tenant, tenant_admin_client

_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "1", "data": {"nodeMeta": {"title": "开始"}},
         "config": {"inputs": [{"name": "q", "type": "string"}]}},
        {"id": "n2", "type": "2", "data": {"nodeMeta": {"title": "结束"}}},
    ],
    "edges": [{"sourceNodeID": "n1", "targetNodeID": "n2"}],
}


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _sql(sql: str, **params) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _listed_app(client: TestClient, headers: dict[str, str], name: str, sale_mode: int) -> str:
    """平台创建应用 + 图 + 上架，并按用例设定 sale_mode。"""
    created = client.post(
        "/api/v1/admin/apps", json={"name": name, "description": "开通用例"}, headers=headers
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["application_id"]
    saved = client.put(
        f"/api/v1/admin/apps/{app_id}/graph",
        json={"graph": _GRAPH, "changelog": "init"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    listed = client.post(
        f"/api/v1/admin/apps/{app_id}/listing", json={"listed": True}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    _sql("UPDATE application SET sale_mode = :m WHERE id = :aid", m=sale_mode, aid=app_id)
    return app_id


def _tenant_site(tenant_client, client: TestClient, auth_headers, code: str):
    create_tenant(client, auth_headers, code=code, name=f"公司{code}")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    return site, headers


def _subscribe(site: TestClient, headers: dict[str, str], app_id: str):
    return site.post(
        "/api/v1/admin/marketplace/subscribe",
        json={"application_id": app_id},
        headers=headers,
    )


def test_subscribe_requires_sale_mode_market(client: TestClient, tenant_client, auth_headers):
    """sale_mode=1（仅运营后台开通）自助订阅必须 422。"""
    app_id = _listed_app(client, auth_headers, "仅后台开通应用", sale_mode=1)
    site, headers = _tenant_site(tenant_client, client, auth_headers, "sub-a")
    response = _subscribe(site, headers, app_id)
    assert response.status_code == 422, response.text
    assert "运营后台" in response.json()["detail"]


def test_subscribe_requires_listed_and_enabled(
    client: TestClient, tenant_client, auth_headers
) -> None:
    app_id = _listed_app(client, auth_headers, "下架用例应用", sale_mode=2)
    site, headers = _tenant_site(tenant_client, client, auth_headers, "sub-b")

    _sql(
        "UPDATE application SET is_listed_in_market = FALSE WHERE id = :aid",
        aid=app_id,
    )
    assert _subscribe(site, headers, app_id).status_code == 422

    _sql(
        "UPDATE application SET is_listed_in_market = TRUE, is_enabled = FALSE WHERE id = :aid",
        aid=app_id,
    )
    response = _subscribe(site, headers, app_id)
    assert response.status_code == 422, response.text
    assert "禁用" in response.json()["detail"]


def test_subscribe_success_and_duplicate(
    client: TestClient, tenant_client, auth_headers
) -> None:
    app_id = _listed_app(client, auth_headers, "市场开通用例", sale_mode=2)
    site, headers = _tenant_site(tenant_client, client, auth_headers, "sub-c")

    response = _subscribe(site, headers, app_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application_id"] == app_id

    my_apps = site.get("/api/v1/admin/marketplace/my-apps", headers=headers)
    assert my_apps.status_code == 200, my_apps.text
    instances = [item for item in my_apps.json() if item["application_id"] == app_id]
    assert instances and instances[0]["status"] == "active"

    duplicate = _subscribe(site, headers, app_id)
    assert duplicate.status_code == 422, duplicate.text


@pytest.mark.parametrize("column,value", [("status", "revoked"), ("expire_time", "past")])
def test_run_blocked_after_instance_invalid(
    client: TestClient, tenant_client, auth_headers, column: str, value: str
) -> None:
    """实例被撤销或过期后运行返回 403。"""
    app_id = _listed_app(client, auth_headers, "失效实例应用", sale_mode=2)
    site, headers = _tenant_site(tenant_client, client, auth_headers, "sub-d")
    subscribed = _subscribe(site, headers, app_id)
    assert subscribed.status_code == 200, subscribed.text
    instance_id = subscribed.json()["instance_id"]

    if column == "status":
        _sql(
            "UPDATE tenant_application_instance SET status = :v WHERE id = :iid",
            v=value,
            iid=instance_id,
        )
    else:
        _sql(
            "UPDATE tenant_application_instance SET expire_time = now() - interval '1 hour' "
            "WHERE id = :iid",
            iid=instance_id,
        )

    run = site.post(
        f"/api/v1/admin/marketplace/applications/{app_id}/run",
        json={"inputs": {"q": "hi"}},
        headers=headers,
    )
    assert run.status_code == 403, run.text
    assert "失效" in run.json()["detail"]

    inputs = site.get(
        f"/api/v1/admin/marketplace/applications/{app_id}/inputs", headers=headers
    )
    assert inputs.status_code == 403, inputs.text


def test_run_requires_subscription(
    client: TestClient, tenant_client, auth_headers
) -> None:
    """未开通运行仍 404（保持原语义）。"""
    app_id = _listed_app(client, auth_headers, "未开通应用", sale_mode=2)
    site, headers = _tenant_site(tenant_client, client, auth_headers, "sub-e")
    run = site.post(
        f"/api/v1/admin/marketplace/applications/{UUID(app_id)}/run",
        json={"inputs": {"q": "hi"}},
        headers=headers,
    )
    assert run.status_code == 404, run.text
