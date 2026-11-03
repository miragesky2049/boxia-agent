"""P3-2 到期提醒 + P3-7 取消/恢复通知：分桶扫描去重与变更通知随批量事务落库。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from internal.application.apps.entitlement_service import EntitlementService
from internal.application.entitlement_notify import (
    CHANGE_NOTICE_ACTION,
    EXPIRY_REMINDER_ACTION,
    NOTICE_MODE_RESTORED,
    NOTICE_MODE_REVOKED,
    EntitlementNotifyService,
)
from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.request_context import RequestContext
from internal.infrastructure.model.audit_log import AuditLogModel
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository

_CONFIG = {"url": "https://example.com/api", "method": "GET"}
_ACTOR_ID = uuid4()
_ACTOR = "ops-admin"


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
    code = f"entn-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"提醒租户{code}"})
    uow.commit()
    return t.id


def _service(uow: SqlAlchemyUnitOfWork) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="adminsystem")
    return EntitlementService(uow, EntitlementRepository(uow.session), context)


def _grant_with_expire(uow: SqlAlchemyUnitOfWork, tenant, expire_time):
    skill_id = uow.resource_repo("skill").create({"name": "临期技能", "config": _CONFIG}).id
    uow.commit()
    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("skill", skill_id)],
            expire_time=expire_time,
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    return skill_id


def _reminder_count(uow: SqlAlchemyUnitOfWork, tenant) -> int:
    return (
        uow.session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(
                AuditLogModel.action == EXPIRY_REMINDER_ACTION,
                AuditLogModel.tenant_id == tenant,
            )
        )
        or 0
    )


def test_scan_buckets_and_dedupe(uow, tenant):
    """剩 2 天的权益落 7/3 桶不落 1 桶；重扫去重零发送；覆盖 app 与资源双表。"""
    now = datetime.now(UTC)
    _grant_with_expire(uow, tenant, now + timedelta(days=2))
    app_id = ApplicationRepository(uow.session).create_application("临期应用", "tenant", tenant)
    uow.commit()
    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("app", app_id)],
            expire_time=now + timedelta(days=2),
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )

    notify = EntitlementNotifyService(uow, EntitlementRepository(uow.session))
    sent = notify.scan_expiry_reminders(now)
    assert sent == {"7": 2, "3": 2, "1": 0}
    assert _reminder_count(uow, tenant) == 4

    again = notify.scan_expiry_reminders(now)
    assert again == {"7": 0, "3": 0, "1": 0}
    assert _reminder_count(uow, tenant) == 4


def test_scan_skips_no_expire_and_revoked(uow, tenant):
    """无到期时间与已撤销权益不提醒。"""
    now = datetime.now(UTC)
    _grant_with_expire(uow, tenant, None)
    expiring = _grant_with_expire(uow, tenant, now + timedelta(hours=12))
    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "revoke",
            [EntitlementItem("skill", expiring)],
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )

    notify = EntitlementNotifyService(uow, EntitlementRepository(uow.session))
    sent = notify.scan_expiry_reminders(now)
    assert sent == {"7": 0, "3": 0, "1": 0}
    assert _reminder_count(uow, tenant) == 0


def _notice_rows(uow: SqlAlchemyUnitOfWork, tenant, notice_mode: str) -> list[dict]:
    rows = (
        uow.session.execute(
            select(AuditLogModel.detail).where(
                AuditLogModel.action == CHANGE_NOTICE_ACTION,
                AuditLogModel.tenant_id == tenant,
            )
        )
        .scalars()
        .all()
    )
    return [detail for detail in rows if detail.get("notice_mode") == notice_mode]


def test_revoke_and_restore_write_change_notices(uow, tenant):
    """P3-7：新开通不发通知；撤销发 revoked、重新 grant 恢复发 restored、active 重复 grant 不再发。"""
    now = datetime.now(UTC)
    skill_id = _grant_with_expire(uow, tenant, now + timedelta(days=30))
    assert _notice_rows(uow, tenant, NOTICE_MODE_REVOKED) == []
    assert _notice_rows(uow, tenant, NOTICE_MODE_RESTORED) == []

    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "revoke",
            [EntitlementItem("skill", skill_id)],
            reason="欠费取消",
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    revoked = _notice_rows(uow, tenant, NOTICE_MODE_REVOKED)
    assert len(revoked) == 1
    assert revoked[0]["reason"] == "欠费取消"
    assert revoked[0]["name"] == "临期技能"
    assert revoked[0]["object_id"] == str(skill_id)

    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("skill", skill_id)],
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    assert len(_notice_rows(uow, tenant, NOTICE_MODE_RESTORED)) == 1

    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("skill", skill_id)],
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    assert len(_notice_rows(uow, tenant, NOTICE_MODE_RESTORED)) == 1
