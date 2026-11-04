"""P3-9 对账作业：三类漂移扫描口径、平台作用域豁免与告警审计落库。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.tasks.entitlement_reconcile import reconcile_task, scan_drift

_CONFIG = {"url": "https://example.com/api", "method": "GET"}


@pytest.fixture()
def uow():
    u = SqlAlchemyUnitOfWork()
    u.apply_scope((), apply_role_filter=False)
    try:
        yield u
    finally:
        u.close()


@pytest.fixture()
def tenant(uow):
    code = f"rec-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"对账租户{code}"})
    uow.commit()
    return t.id


def _make_resource(uow, *, platform: bool, review_status: str = "approved", tenant_id=None):
    rid = uow.resource_repo("skill").create({"name": "对账技能", "config": _CONFIG}).id
    owner_type = "platform" if platform else "tenant"
    uow.session.execute(
        text("UPDATE resource SET owner_type=:ot, owner_id=:oid, review_status=:rs WHERE id=:id"),
        {"ot": owner_type, "oid": tenant_id, "rs": review_status, "id": rid},
    )
    uow.commit()
    return rid


def _grant(uow, tenant_id, resource_type, resource_id):
    uow.session.execute(
        text(
            "INSERT INTO resource_grants (id, resource_type, resource_id, tenant_id, subject_type) "
            "VALUES (:id, :rt, :rid, :tid, 'tenant')"
        ),
        {"id": uuid4(), "rt": resource_type, "rid": resource_id, "tid": tenant_id},
    )
    uow.commit()


def _entitlement(uow, tenant_id, resource_id, *, status="active", expire=None):
    uow.session.execute(
        text(
            "INSERT INTO tenant_resource_entitlement (id, resource_id, tenant_id, granted_at, status, "
            "auth_source, auth_type, expire_time, quota_json, remark) "
            "VALUES (:id, :rid, :tid, NOW(), :status, 'OPS', 'FORMAL', :expire, '{}'::jsonb, '')"
        ),
        {
            "id": uuid4(),
            "rid": resource_id,
            "tid": tenant_id,
            "status": status,
            "expire": expire,
        },
    )
    uow.commit()


def _application(uow):
    aid = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, visibility_mode, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '对账应用', '', TRUE, FALSE, 'all', 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": aid},
    )
    uow.commit()
    return aid


def _instance(uow, tenant_id, app_id, *, status="active"):
    uow.session.execute(
        text(
            "INSERT INTO tenant_application_instance "
            "(id, tenant_id, application_id, status, source, overrides) "
            "VALUES (:id, :tid, :aid, :status, 'granted', '{}'::jsonb)"
        ),
        {"id": uuid4(), "tid": tenant_id, "aid": app_id, "status": status},
    )
    uow.commit()


def test_dangling_grant_until_entitlement_effective(uow, tenant):
    """平台资源有授权无权益 → 计入；权益生效即消除；过期窗口口径同读侧。"""
    skill_id = _make_resource(uow, platform=True)
    _grant(uow, tenant, "skill", skill_id)

    drift = scan_drift(uow.session)
    assert drift["dangling_grants"]["count"] == 1
    assert drift["dangling_grants"]["samples"][0]["resource_id"] == str(skill_id)

    future = datetime.now(UTC) + timedelta(days=1)
    _entitlement(uow, tenant, skill_id, expire=future)
    assert scan_drift(uow.session)["dangling_grants"]["count"] == 0

    uow.session.execute(
        text("UPDATE tenant_resource_entitlement SET expire_time = NOW() - interval '1 day'")
    )
    uow.commit()
    assert scan_drift(uow.session)["dangling_grants"]["count"] == 1


def test_exempt_tenant_owned_and_platform_scope(uow, tenant):
    """租户自有资源不需要开通权益；平台租户自身的授权不参与租户对账。"""
    own_skill = _make_resource(uow, platform=False, tenant_id=tenant)
    _grant(uow, tenant, "skill", own_skill)
    platform_skill = _make_resource(uow, platform=True)
    _grant(uow, PLATFORM_TENANT_ID, "skill", platform_skill)

    drift = scan_drift(uow.session)
    assert drift["dangling_grants"]["count"] == 0
    assert drift["total"] == 0


def test_unapproved_and_orphan_grants(uow, tenant):
    """未过审授权与指向已删对象的授权分列计数；权益侧有 FK+CASCADE 不存在悬挂。"""
    pending_skill = _make_resource(uow, platform=True, review_status="pending")
    _grant(uow, tenant, "skill", pending_skill)
    _entitlement(uow, tenant, pending_skill)

    _grant(uow, tenant, "skill", uuid4())

    drift = scan_drift(uow.session)
    assert drift["unapproved_grants"]["count"] == 1
    assert drift["unapproved_grants"]["samples"][0]["review_status"] == "pending"
    assert drift["orphan_grants"]["count"] == 1
    assert drift["dangling_grants"]["count"] == 0
    assert set(drift) >= {"dangling_grants", "unapproved_grants", "orphan_grants"}
    assert "补开通权益" in drift["suggestion"]


def test_app_grant_requires_active_instance(uow, tenant):
    """app 类授权无有效实例计入 dangling；实例存在即消除；应用已删归 orphan_grants。"""
    app_id = _application(uow)
    _grant(uow, tenant, "app", app_id)
    assert scan_drift(uow.session)["dangling_grants"]["count"] == 1

    _instance(uow, tenant, app_id)
    assert scan_drift(uow.session)["dangling_grants"]["count"] == 0

    _grant(uow, tenant, "app", uuid4())
    drift = scan_drift(uow.session)
    assert drift["dangling_grants"]["count"] == 0
    assert drift["orphan_grants"]["count"] == 1


def test_task_writes_reconcile_audit(uow, tenant):
    """任务把汇总写 audit_logs(action=entitlement.reconcile)，detail 含四类计数与建议。"""
    skill_id = _make_resource(uow, platform=True)
    _grant(uow, tenant, "skill", skill_id)

    result = reconcile_task()
    assert result["total"] == 1
    assert set(result) >= {
        "dangling_grants",
        "unapproved_grants",
        "orphan_grants",
        "suggestion",
        "audit_id",
    }
    detail = uow.session.execute(
        text("SELECT detail FROM audit_logs WHERE action = 'entitlement.reconcile' AND id = :id"),
        {"id": UUID(result["audit_id"])},
    ).scalar_one()
    assert detail["dangling_grants"]["count"] == 1
    assert detail["total"] == 1
