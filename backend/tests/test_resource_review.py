"""资源审核闭环（P1-9）：租户自建 pending、平台审核放行/驳回、职责分离与权限门槛。"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.database import get_engine
from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    list_roles,
    tenant_admin_client,
)

_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


def _create_platform_admin(
    client: TestClient, auth_headers: dict[str, str], username: str, role_code: str
) -> dict[str, str]:
    """在平台站点创建指定角色的管理员并登录，返回鉴权头。"""
    roles = {
        item["code"]: item
        for item in client.get("/api/v1/admin/roles", headers=auth_headers).json()
    }
    created = client.post(
        "/api/v1/admin/admin-users",
        json={
            "username": username,
            "password": USER_PASSWORD,
            "display_name": username,
            "role_id": roles[role_code]["id"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_platform_tool(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        "/api/v1/admin/resources",
        json={"type": "tool", "name": name, "config": _TOOL_CONFIG},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["resource_id"]


def _review(
    client: TestClient,
    headers: dict[str, str],
    resource_id: str,
    decision: str,
    remark: str = "",
):
    return client.post(
        f"/api/v1/admin/resources/{resource_id}/review",
        json={"decision": decision, "remark": remark},
        headers=headers,
    )


def _my_resources(site: TestClient, headers: dict[str, str]) -> list[dict]:
    response = site.get("/api/v1/admin/my-resources", params={"type": "tool"}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _create_my_tool(site: TestClient, headers: dict[str, str], name: str) -> str:
    response = site.post(
        "/api/v1/admin/my-resources",
        json={"type": "tool", "name": name, "config": _TOOL_CONFIG},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["resource_id"]


def _add_role_grant(site: TestClient, headers: dict[str, str], role_id: str, resource_id: str):
    return site.post(
        f"/api/v1/admin/roles/{role_id}/grants/tool",
        json={"resource_ids": [resource_id]},
        headers=headers,
    )


def test_platform_created_tool_is_approved(client: TestClient, auth_headers, tenant_client) -> None:
    tool_id = _create_platform_tool(client, auth_headers, "平台自建免审")
    detail = client.get(f"/api/v1/admin/resources/{tool_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["review_status"] == "approved"

    pending = client.get(
        "/api/v1/admin/resources", params={"review_status": "pending"}, headers=auth_headers
    )
    assert tool_id not in {item["id"] for item in pending.json()}


def test_tenant_created_tool_pending_then_review_flow(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """租户自建默认 pending 且不可授权；approve 后放行；reject 后再次拦截。"""
    tenant = create_tenant(client, auth_headers, code="rreview", name="审核公司")
    site, headers, _ = tenant_admin_client(tenant_client, "rreview")
    viewer_id = list_roles(site, headers)["viewer"]["id"]

    tool_id = _create_my_tool(site, headers, "租户自建待审")
    mine = {item["id"]: item for item in _my_resources(site, headers)}
    assert mine[tool_id]["review_status"] == "pending"

    blocked = _add_role_grant(site, headers, viewer_id, tool_id)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["code"] == "RESOURCE_NOT_APPROVED"

    approved = _review(client, auth_headers, tool_id, "approve", "内容合规")
    assert approved.status_code == 200, approved.text
    assert approved.json()["review_status"] == "approved"
    added = _add_role_grant(site, headers, viewer_id, tool_id)
    assert added.status_code == 200, added.text
    assert added.json()["updated"] == 1

    rejected = _review(client, auth_headers, tool_id, "reject", "发现风险")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["review_status"] == "rejected"
    again = _add_role_grant(site, headers, viewer_id, tool_id)
    assert again.status_code == 422, again.text
    assert again.json()["code"] == "RESOURCE_NOT_APPROVED"

    mine = {item["id"]: item for item in _my_resources(site, headers)}
    assert mine[tool_id]["review_status"] == "rejected"
    assert mine[tool_id]["review_remark"] == "发现风险"


def test_review_requires_permission(client: TestClient, auth_headers) -> None:
    """平台 viewer 无 button:resource:review → 403。"""
    viewer_headers = _create_platform_admin(client, auth_headers, "rr-viewer", "viewer")
    tool_id = _create_platform_tool(client, auth_headers, "审核权限门槛")
    response = _review(client, viewer_headers, tool_id, "approve")
    assert response.status_code == 403, response.text


def test_tenant_principal_cannot_review_platform_side(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, code="rrscope", name="越界公司")
    site, headers, _ = tenant_admin_client(tenant_client, "rrscope")
    tool_id = _create_platform_tool(client, auth_headers, "租户越权审核")
    response = _review(site, headers, tool_id, "approve")
    assert response.status_code == 403, response.text


def test_self_review_forbidden_and_legacy_bypass(client: TestClient, auth_headers) -> None:
    """创建人自审 403 SELF_REVIEW_FORBIDDEN；换人可审；created_by 为 NULL 的历史资源放行。"""
    admin_id = _create_platform_admin(client, auth_headers, "rr-creator", "admin")
    reviewer_id = _create_platform_admin(client, auth_headers, "rr-reviewer", "admin")
    tool_id = _create_platform_tool(client, admin_id, "自审拦截")

    blocked = _review(client, admin_id, tool_id, "approve")
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["code"] == "SELF_REVIEW_FORBIDDEN"

    allowed = _review(client, reviewer_id, tool_id, "approve")
    assert allowed.status_code == 200, allowed.text

    legacy_tool_id = _create_platform_tool(client, admin_id, "历史资源补审")
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE resource SET created_by = NULL WHERE id = :rid"),
            {"rid": legacy_tool_id},
        )
    legacy = _review(client, admin_id, legacy_tool_id, "approve")
    assert legacy.status_code == 200, legacy.text
