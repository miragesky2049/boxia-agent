"""P3-11 宽限期：expired 后 grace_days 只读窗口、超期读作 revoked 与定时流转落库。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.entity.entitlement import effective_status
from internal.domain.entity.request_context import RequestContext
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository
from internal.infrastructure.tasks.entitlement_tasks import process_grace_revoked_task

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
    code = f"grace-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"宽限期租户{code}"})
    uow.commit()
    return t.id


def _skill(uow) -> object:
    rid = uow.resource_repo("skill").create({"name": "宽限技能", "config": _CONFIG}).id
    uow.commit()
    return rid


def _entitlement(uow, tenant, resource_id, *, status, expire_days):
    uow.session.execute(
        text(
            "INSERT INTO tenant_resource_entitlement (id, resource_id, tenant_id, granted_at, "
            "status, auth_source, auth_type, expire_time, quota_json, remark) "
            "VALUES (:id, :rid, :tid, NOW(), :status, 'OPS', 'FORMAL', :expire, '{}'::jsonb, '')"
        ),
        {
            "id": uuid4(),
            "rid": resource_id,
            "tid": tenant,
            "status": status,
            "expire": datetime.now(UTC) - timedelta(days=expire_days),
        },
    )
    uow.commit()


def _row_status(uow, resource_id) -> str:
    return uow.session.execute(
        text("SELECT status FROM tenant_resource_entitlement WHERE resource_id = :rid"),
        {"rid": resource_id},
    ).scalar_one()


def _overdue_application_instance(uow, tenant) -> object:
    aid = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '宽限应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": aid},
    )
    uow.session.execute(
        text(
            "INSERT INTO tenant_application_instance "
            "(id, tenant_id, application_id, status, source, overrides, expire_time) "
            "VALUES (:id, :tid, :aid, 'expired', 'granted', '{}'::jsonb, :expire)"
        ),
        {
            "id": uuid4(),
            "tid": tenant,
            "aid": aid,
            "expire": datetime.now(UTC) - timedelta(days=5),
        },
    )
    uow.commit()
    return aid


def _service(uow, grace_days: int) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="system")
    return EntitlementService(
        uow, EntitlementRepository(uow.session), context, grace_days=grace_days
    )


def test_effective_status_grace_windows():
    """纯函数口径：窗口内 expired，超窗 revoked，grace=0 行为不变。"""
    now = datetime.now(UTC)
    expired_2d = now - timedelta(days=2)
    assert effective_status("active", None, expired_2d, now) == "expired"
    assert effective_status("active", None, expired_2d, now, 30) == "expired"
    assert effective_status("active", None, expired_2d, now, 1) == "revoked"
    assert effective_status("expired", None, expired_2d, now, 30) == "expired"
    assert effective_status("expired", None, expired_2d, now, 1) == "revoked"
    assert effective_status("revoked", None, expired_2d, now, 1) == "revoked"


def test_read_side_grace_via_repository(uow, tenant):
    """读侧随仓储 grace_days 配置：窗口内显示 expired，超窗显示 revoked。"""
    skill_id = _skill(uow)
    _entitlement(uow, tenant, skill_id, status="expired", expire_days=5)

    within = EntitlementRepository(uow.session, grace_days=30).get(tenant, "skill", skill_id)
    beyond = EntitlementRepository(uow.session, grace_days=3).get(tenant, "skill", skill_id)
    legacy = EntitlementRepository(uow.session).get(tenant, "skill", skill_id)
    assert within.status == "expired"
    assert beyond.status == "revoked"
    assert legacy.status == "expired"


def test_sweep_persists_only_overdue(uow, tenant):
    """流转任务只把超窗行落库 revoked，窗口内行保持 expired；grace=0 整体关闭。"""
    in_window = _skill(uow)
    overdue = _skill(uow)
    _entitlement(uow, tenant, in_window, status="expired", expire_days=2)
    _entitlement(uow, tenant, overdue, status="expired", expire_days=5)
    overdue_app = _overdue_application_instance(uow, tenant)

    closed = _service(uow, grace_days=0)
    assert closed.process_grace_revoked(datetime.now(UTC)) == 0

    count = _service(uow, grace_days=3).process_grace_revoked(datetime.now(UTC))
    uow.commit()
    assert count == 2
    assert _row_status(uow, overdue) == "revoked"
    assert _row_status(uow, in_window) == "expired"
    app_status = uow.session.execute(
        text("SELECT status FROM tenant_application_instance WHERE application_id = :aid"),
        {"aid": overdue_app},
    ).scalar_one()
    assert app_status == "revoked"


def test_task_end_to_end_with_default_grace(uow, tenant):
    """任务按 settings 默认 grace_days=30 装配：40 天前行落库 revoked，3 天内行不动。"""
    beyond = _skill(uow)
    recent = _skill(uow)
    _entitlement(uow, tenant, beyond, status="expired", expire_days=40)
    _entitlement(uow, tenant, recent, status="expired", expire_days=3)

    count = process_grace_revoked_task()
    assert count >= 1
    assert _row_status(uow, beyond) == "revoked"
    assert _row_status(uow, recent) == "expired"
