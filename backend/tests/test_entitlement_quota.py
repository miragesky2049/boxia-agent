"""P3-10 配额执行点：seats/runs 判定、不限/非法口径与 QUOTA_EXCEEDED 422。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import (
    NotFoundError,
    QuotaExceededError,
    ResourceNotEntitledError,
    ValidationError,
)
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository

_CONFIG = {"url": "https://example.com/api", "method": "GET"}
_ACTOR_ID = uuid4()


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
    code = f"quota-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"配额租户{code}"})
    uow.commit()
    return t.id


def _service(uow: SqlAlchemyUnitOfWork) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="platform")
    return EntitlementService(uow, EntitlementRepository(uow.session), context)


def _grant(uow, tenant, object_type, object_id, *, quota=None, start_time=None):
    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem(object_type, object_id)],
            quota=quota,
            start_time=start_time,
            actor_id=_ACTOR_ID,
            actor_username="ops-admin",
        )
    )


def _skill(uow) -> object:
    rid = uow.resource_repo("skill").create({"name": "配额技能", "config": _CONFIG}).id
    uow.commit()
    return rid


def _application(uow) -> object:
    aid = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '配额应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": aid},
    )
    uow.commit()
    return aid


def test_seats_limit_enforced(uow, tenant):
    """seats=2：1+1 放行、2+0 放行、2+1 超限 422 QUOTA_EXCEEDED。"""
    skill_id = _skill(uow)
    _grant(uow, tenant, "skill", skill_id, quota={"seats": 2})

    service = _service(uow)
    service.check_quota(tenant, "skill", skill_id, dimension="seats", used=1)
    service.check_quota(tenant, "skill", skill_id, dimension="seats", used=2, amount=0)
    with pytest.raises(QuotaExceededError, match="配额超限"):
        service.check_quota(tenant, "skill", skill_id, dimension="seats", used=2)
    assert QuotaExceededError.status_code == 422


def test_unlimited_dimensions(uow, tenant):
    """runs=0、缺 seats 键、其他键（qps）均视为不限；runs 正数正常判定。"""
    skill_id = _skill(uow)
    _grant(uow, tenant, "skill", skill_id, quota={"runs": 0, "qps": 10})
    _service(uow).check_quota(tenant, "skill", skill_id, dimension="runs", used=10**9)
    _service(uow).check_quota(tenant, "skill", skill_id, dimension="seats", used=10**9)

    other_id = _skill(uow)
    _grant(uow, tenant, "skill", other_id, quota={"runs": 3})
    with pytest.raises(QuotaExceededError):
        _service(uow).check_quota(tenant, "skill", other_id, dimension="runs", used=3)


def test_app_store_read_path(uow, tenant):
    """app 存储（tenant_application_instance）与资源存储走同一判定口径。"""
    app_id = _application(uow)
    _grant(uow, tenant, "app", app_id, quota={"seats": 1})
    _service(uow).check_quota(tenant, "app", app_id, dimension="seats", used=0)
    with pytest.raises(QuotaExceededError):
        _service(uow).check_quota(tenant, "app", app_id, dimension="seats", used=1)


def test_no_or_pending_entitlement(uow, tenant):
    """无权益 404；未生效（wait_effect）RESOURCE_NOT_ENTITLED。"""
    skill_id = _skill(uow)
    with pytest.raises(NotFoundError):
        _service(uow).check_quota(tenant, "skill", skill_id, dimension="seats", used=0)

    _grant(
        uow,
        tenant,
        "skill",
        skill_id,
        quota={"seats": 1},
        start_time=datetime.now(UTC) + timedelta(days=1),
    )
    with pytest.raises(ResourceNotEntitledError, match="wait_effect"):
        _service(uow).check_quota(tenant, "skill", skill_id, dimension="seats", used=0)


def test_invalid_inputs(uow, tenant):
    """维度不支持、配额配置非法、used 非法均 422，不落判定。"""
    skill_id = _skill(uow)
    _grant(uow, tenant, "skill", skill_id, quota={"seats": "x"})
    service = _service(uow)
    with pytest.raises(ValidationError, match="不支持的配额维度"):
        service.check_quota(tenant, "skill", skill_id, dimension="qps", used=0)
    with pytest.raises(ValidationError, match="非负整数"):
        service.check_quota(tenant, "skill", skill_id, dimension="seats", used=0)

    bad_id = _skill(uow)
    _grant(uow, tenant, "skill", bad_id, quota={"seats": -1})
    with pytest.raises(ValidationError, match="非法"):
        _service(uow).check_quota(tenant, "skill", bad_id, dimension="seats", used=0)
    with pytest.raises(ValidationError, match="used"):
        _service(uow).check_quota(tenant, "skill", bad_id, dimension="seats", used=-1)
