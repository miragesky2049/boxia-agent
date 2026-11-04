"""P1-11 entitlement.batch 审计：一次批量操作可由 before/after 快照与三组计数完整还原。"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from internal.infrastructure.model.audit_log import AuditLogModel
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from tests.helpers import create_tenant

BASE = "/api/v1/admin/entitlements"


@pytest.fixture()
def env(client: TestClient, auth_headers: dict[str, str]) -> dict:
    """租户 + skill 资源；审计行按 tenant_id 归属该租户，天然与用例隔离。"""
    tenant = create_tenant(client, auth_headers, code="entaudit", name="权益审计租户")
    skill_resp = client.post(
        "/api/v1/admin/resources",
        json={
            "type": "skill",
            "name": "权益审计技能",
            "config": {"url": "https://example.com/api", "method": "GET"},
        },
        headers=auth_headers,
    )
    assert skill_resp.status_code == 201, skill_resp.text
    return {"tenant_id": tenant["id"], "skill_id": skill_resp.json()["resource_id"]}


def _batch(client: TestClient, auth_headers: dict, env: dict, mode: str, reason: str) -> dict:
    resp = client.post(
        f"{BASE}/batch",
        json={
            "tenant_id": env["tenant_id"],
            "mode": mode,
            "items": [{"object_type": "skill", "object_id": env["skill_id"]}],
            "reason": reason,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _latest_audit(tenant_id: str) -> AuditLogModel:
    uow = SqlAlchemyUnitOfWork()
    try:
        row = uow.session.scalars(
            select(AuditLogModel)
            .where(
                AuditLogModel.action == "entitlement.batch",
                AuditLogModel.tenant_id == UUID(tenant_id),
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .limit(1)
        ).one()
        return row
    finally:
        uow.close()


def test_grant_audit_restores_full_operation(client: TestClient, auth_headers, env):
    """首次开通：before=None→after=active，add=1；重复开通：unchanged=1 且快照仍 active。"""
    first = _batch(client, auth_headers, env, "grant", "审计开通")
    assert first == {"updated": 1, "failed": [], "affected_role_grants": 0}

    row = _latest_audit(env["tenant_id"])
    assert row.resource_type == "entitlement"
    assert row.resource_id == env["tenant_id"]
    assert row.actor_username
    assert row.user_agent
    detail = row.detail
    assert detail["mode"] == "grant"
    assert detail["tenant_id"] == env["tenant_id"]
    assert detail["reason"] == "审计开通"
    assert detail["items"] == [{"object_type": "skill", "object_id": env["skill_id"]}]
    assert (detail["add"], detail["remove"], detail["unchanged"]) == (1, 0, 0)
    assert detail["updated"] == 1 and detail["affected_role_grants"] == 0
    assert detail["before"] == [None]

    snapshot = detail["after"][0]
    assert snapshot["object_type"] == "skill"
    assert snapshot["object_id"] == env["skill_id"]
    assert snapshot["name"] == "权益审计技能"
    assert snapshot["status"] == "active"
    assert snapshot["auth_source"] == "OPS"
    assert snapshot["auth_type"] == "FORMAL"
    assert snapshot["remark"] == "审计开通"
    assert snapshot["start_time"] is None and snapshot["expire_time"] is None

    _batch(client, auth_headers, env, "grant", "审计重复开通")
    replay = _latest_audit(env["tenant_id"]).detail
    assert (replay["add"], replay["remove"], replay["unchanged"]) == (0, 0, 1)
    assert replay["before"][0]["status"] == "active"
    assert replay["after"][0]["status"] == "active"


def test_revoke_audit_restores_soft_invalidate(client: TestClient, auth_headers, env):
    """取消：before=active→after=revoked，remove=1，remark 落 reason。"""
    _batch(client, auth_headers, env, "grant", "审计开通")
    result = _batch(client, auth_headers, env, "revoke", "审计取消")
    assert result == {"updated": 1, "failed": [], "affected_role_grants": 0}

    detail = _latest_audit(env["tenant_id"]).detail
    assert detail["mode"] == "revoke"
    assert detail["reason"] == "审计取消"
    assert (detail["add"], detail["remove"], detail["unchanged"]) == (0, 1, 0)
    assert detail["before"][0]["status"] == "active"
    assert detail["after"][0]["status"] == "revoked"
    assert detail["after"][0]["remark"] == "审计取消"
