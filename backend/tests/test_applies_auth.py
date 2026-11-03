"""申请单鉴权与认领归属：运营端点仅平台作用域可用，认领 CAS 落库 sales_user_id。"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.database import get_engine
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from tests.helpers import create_tenant, tenant_admin_client


def _sql(sql: str, **params):
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params)


def _app(client: TestClient, auth_headers: dict[str, str]) -> str:
    created = client.post(
        "/api/v1/admin/apps",
        json={"name": "申请单鉴权用例", "description": "P0-6"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["application_id"]


def _site(tenant_client, client: TestClient, auth_headers: dict[str, str], code: str):
    create_tenant(client, auth_headers, code=code, name=f"公司{code}")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    return site, headers


def _submit(site: TestClient, headers: dict[str, str], app_id: str) -> str:
    resp = site.post(
        "/api/v1/admin/applies",
        json={"application_id": app_id, "apply_type": "TRIAL", "contact": "张三"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.parametrize(
    "method,path_template,payload",
    [
        ("get", "pass-pending", None),
        ("get", "sales-mine", None),
        ("post", "{apply_id}/claim", {}),
        ("post", "{apply_id}/pass", {}),
        ("post", "{apply_id}/reject", {"audit_msg": "不符合"}),
    ],
)
def test_tenant_admin_blocked_from_ops_endpoints(
    client: TestClient, tenant_client, auth_headers, method: str, path_template: str, payload
) -> None:
    """租户子域名管理员调用运营侧申请单端点必须 403（仅产品级平台可用）。"""
    app_id = _app(client, auth_headers)
    site, headers = _site(tenant_client, client, auth_headers, "apply-a")
    apply_id = _submit(site, headers, app_id)
    url = f"/api/v1/admin/applies/{path_template.format(apply_id=apply_id)}"
    request = getattr(site, method)
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["json"] = payload
    response = request(url, **kwargs)
    assert response.status_code == 403, response.text
    assert "产品级" in response.json()["detail"]


def test_claim_persists_sales_user_and_visible_in_sales_mine(
    client: TestClient, tenant_client, auth_headers
) -> None:
    """平台认领成功 200：sales_user_id 落库，sales-mine 可查。"""
    app_id = _app(client, auth_headers)
    site, headers = _site(tenant_client, client, auth_headers, "apply-b")
    apply_id = _submit(site, headers, app_id)

    claim = client.post(f"/api/v1/admin/applies/{apply_id}/claim", headers=auth_headers)
    assert claim.status_code == 200, claim.text

    sales = client.get("/api/v1/admin/applies/sales-mine", headers=auth_headers)
    assert sales.status_code == 200, sales.text
    assert apply_id in [item["id"] for item in sales.json()]

    row = _sql(
        "SELECT status, sales_user_id FROM application_apply WHERE id = :id",
        id=apply_id,
    ).first()
    assert row.status == "HANDLING"
    assert row.sales_user_id is not None


def test_claim_rejected_when_not_submitted(client: TestClient, tenant_client, auth_headers) -> None:
    """重复认领：状态已 HANDLING，第二人 422。"""
    app_id = _app(client, auth_headers)
    site, headers = _site(tenant_client, client, auth_headers, "apply-c")
    apply_id = _submit(site, headers, app_id)
    first = client.post(f"/api/v1/admin/applies/{apply_id}/claim", headers=auth_headers)
    assert first.status_code == 200, first.text

    second = client.post(f"/api/v1/admin/applies/{apply_id}/claim", headers=auth_headers)
    assert second.status_code == 422, second.text
    assert "认领" in second.json()["detail"]


def test_claim_apply_cas_returns_false_when_status_raced() -> None:
    """仓储层 CAS：读取后状态被他人变更时 claim_apply 返回 False，不覆盖归属。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        app_id = ApplicationRepository(uow.session).create_application(
            "CAS用例应用", "platform", None, description="认领竞态"
        )
        apply_id = AuthRepository(uow.session).create_apply(
            {
                "tenant_id": UUID("00000000-0000-0000-0000-000000000000"),
                "application_id": app_id,
                "apply_type": "TRIAL",
                "status": "SUBMITTED",
                "expect_text": "",
                "contact": "李四",
                "sales_user_id": None,
                "created_by": None,
            }
        )
        uow.commit()

        _sql("UPDATE application_apply SET status = 'HANDLING' WHERE id = :id", id=str(apply_id))
        assert AuthRepository(uow.session).claim_apply(apply_id, new_uuid()) is False
    finally:
        uow.rollback()
        uow.close()


def test_tenant_can_list_own_applies(client: TestClient, tenant_client, auth_headers) -> None:
    """租户侧 /applies/mine 不受平台限制，返回自己的申请记录。"""
    app_id = _app(client, auth_headers)
    site, headers = _site(tenant_client, client, auth_headers, "apply-d")
    apply_id = _submit(site, headers, app_id)
    mine = site.get("/api/v1/admin/applies/mine", headers=headers)
    assert mine.status_code == 200, mine.text
    assert apply_id in [item["id"] for item in mine.json()]
