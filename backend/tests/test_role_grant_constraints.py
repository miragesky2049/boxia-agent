"""角色授权约束（P1-8）：授权≠开通、审核状态与弃用只拦截新授权，已有授权仍可见可撤。"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.database import get_engine
from tests.helpers import (
    create_tenant,
    grant_resource,
    list_roles,
    tenant_admin_client,
)

_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


def _run_sql(statement: str, **params: Any) -> None:
    """直写库：审核置 pending / 权益状态与窗口的 API 入口在 P1-9 之后才有，先以 SQL 构造。"""
    with get_engine().begin() as conn:
        conn.execute(text(statement), params)


def _tenant_env(
    client: TestClient, auth_headers: dict[str, str], tenant_client, code: str
) -> tuple[dict, TestClient, dict[str, str], dict]:
    tenant = create_tenant(client, auth_headers, code=code, name=f"{code} 公司")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    return tenant, site, headers, list_roles(site, headers)


def _create_platform_tool(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        "/api/v1/admin/resources",
        json={"type": "tool", "name": name, "config": _TOOL_CONFIG},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["resource_id"]


def _open_entitlement(
    client: TestClient, headers: dict[str, str], resource_id: str, tenant_id: str
) -> None:
    """开通租户权益（tenant_resource_entitlement 单表）。"""
    response = client.post(
        f"/api/v1/admin/resources/{resource_id}/grants",
        json={"tenant_id": tenant_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _deliver_to_role(
    client: TestClient,
    headers: dict[str, str],
    resource_id: str,
    tenant_id: str,
    role_id: str,
) -> None:
    """平台侧把资源下发给租户角色（复数 resource_grants）。"""
    grant_resource(
        client,
        headers,
        resource_type="tool",
        resource_id=resource_id,
        grants=[{"tenant_id": tenant_id, "role_id": role_id}],
    )


def _add_role_grant(site: TestClient, headers: dict[str, str], role_id: str, resource_id: str):
    return site.post(
        f"/api/v1/admin/roles/{role_id}/grants/tool",
        json={"resource_ids": [resource_id]},
        headers=headers,
    )


def _role_resource_ids(
    site: TestClient,
    headers: dict[str, str],
    role_id: str,
    *,
    granted_only: bool,
) -> set[str]:
    response = site.get(
        f"/api/v1/admin/roles/{role_id}/grants",
        params={
            "resource_type": "tool",
            "granted_only": granted_only,
            "page": 1,
            "page_size": 100,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {item["resource_id"] for item in response.json()["items"]}


def test_platform_tool_requires_opened_entitlement(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """已下发但未开通权益的平台资源：不进候选、不能被授权；开通后两者恢复。"""
    tenant, site, headers, roles = _tenant_env(client, auth_headers, tenant_client, "rgentitled")
    viewer_id = roles["viewer"]["id"]
    admin_id = roles["admin"]["id"]
    tool_id = _create_platform_tool(client, auth_headers, "权益门槛工具")
    _deliver_to_role(client, auth_headers, tool_id, tenant["id"], admin_id)

    assert tool_id not in _role_resource_ids(site, headers, viewer_id, granted_only=False)
    rejected = _add_role_grant(site, headers, viewer_id, tool_id)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "RESOURCE_NOT_ENTITLED"

    _open_entitlement(client, auth_headers, tool_id, tenant["id"])
    assert tool_id in _role_resource_ids(site, headers, viewer_id, granted_only=False)
    added = _add_role_grant(site, headers, viewer_id, tool_id)
    assert added.status_code == 200, added.text
    assert added.json()["updated"] == 1


def test_pending_platform_tool_blocked(client: TestClient, auth_headers, tenant_client) -> None:
    """权益已开通但审核未通过：拦截并给专属码；通过后放行。"""
    tenant, site, headers, roles = _tenant_env(client, auth_headers, tenant_client, "rgpending")
    viewer_id = roles["viewer"]["id"]
    admin_id = roles["admin"]["id"]
    tool_id = _create_platform_tool(client, auth_headers, "待审平台工具")
    _deliver_to_role(client, auth_headers, tool_id, tenant["id"], admin_id)
    _open_entitlement(client, auth_headers, tool_id, tenant["id"])
    _run_sql("UPDATE resource SET review_status = 'pending' WHERE id = :rid", rid=tool_id)

    assert tool_id not in _role_resource_ids(site, headers, viewer_id, granted_only=False)
    rejected = _add_role_grant(site, headers, viewer_id, tool_id)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "RESOURCE_NOT_APPROVED"

    _run_sql("UPDATE resource SET review_status = 'approved' WHERE id = :rid", rid=tool_id)
    added = _add_role_grant(site, headers, viewer_id, tool_id)
    assert added.status_code == 200, added.text
    assert added.json()["updated"] == 1


def test_entitlement_status_and_window_gate_new_grants(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """权益软失效（revoked）与过期窗口按读侧语义拦截，恢复后放行。"""
    tenant, site, headers, roles = _tenant_env(client, auth_headers, tenant_client, "rgwindow")
    viewer_id = roles["viewer"]["id"]
    tool_id = _create_platform_tool(client, auth_headers, "状态窗口工具")
    _deliver_to_role(client, auth_headers, tool_id, tenant["id"], viewer_id)
    _open_entitlement(client, auth_headers, tool_id, tenant["id"])

    _run_sql(
        "UPDATE tenant_resource_entitlement SET status = 'revoked' "
        "WHERE resource_id = :rid AND tenant_id = :tid",
        rid=tool_id,
        tid=tenant["id"],
    )
    rejected = _add_role_grant(site, headers, viewer_id, tool_id)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "RESOURCE_NOT_ENTITLED"

    _run_sql(
        "UPDATE tenant_resource_entitlement SET status = 'active' WHERE resource_id = :rid AND tenant_id = :tid",
        rid=tool_id,
        tid=tenant["id"],
    )
    restored = _add_role_grant(site, headers, viewer_id, tool_id)
    assert restored.status_code == 200, restored.text

    _run_sql(
        "UPDATE tenant_resource_entitlement SET expire_time = NOW() - INTERVAL '1 minute' "
        "WHERE resource_id = :rid AND tenant_id = :tid",
        rid=tool_id,
        tid=tenant["id"],
    )
    expired = _add_role_grant(site, headers, viewer_id, tool_id)
    assert expired.status_code == 422, expired.text
    assert expired.json()["code"] == "RESOURCE_NOT_ENTITLED"
    assert tool_id not in _role_resource_ids(site, headers, viewer_id, granted_only=False)

    _run_sql(
        "UPDATE tenant_resource_entitlement SET expire_time = NULL "
        "WHERE resource_id = :rid AND tenant_id = :tid",
        rid=tool_id,
        tid=tenant["id"],
    )
    assert tool_id in _role_resource_ids(site, headers, viewer_id, granted_only=False)


def test_deprecated_blocks_new_grants_but_existing_stay_visible(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """弃用只拦新授权：已有授权仍在授权页可见、可撤销；候选集隐藏。"""
    tenant, site, headers, roles = _tenant_env(client, auth_headers, tenant_client, "rgdeprec")
    viewer_id = roles["viewer"]["id"]
    admin_id = roles["admin"]["id"]
    tool_id = _create_platform_tool(client, auth_headers, "弃用拦截工具")
    _deliver_to_role(client, auth_headers, tool_id, tenant["id"], admin_id)
    _open_entitlement(client, auth_headers, tool_id, tenant["id"])
    added = _add_role_grant(site, headers, viewer_id, tool_id)
    assert added.status_code == 200, added.text
    assert added.json()["updated"] == 1

    patched = client.patch(
        f"/api/v1/admin/resources/{tool_id}",
        json={"is_deprecated": True},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    assert tool_id in _role_resource_ids(site, headers, viewer_id, granted_only=True)
    assert tool_id not in _role_resource_ids(site, headers, viewer_id, granted_only=False)
    blocked = _add_role_grant(site, headers, admin_id, tool_id)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["code"] == "RESOURCE_DEPRECATED"

    removed = site.delete(f"/api/v1/admin/roles/{viewer_id}/grants/tool/{tool_id}", headers=headers)
    assert removed.status_code == 204, removed.text
