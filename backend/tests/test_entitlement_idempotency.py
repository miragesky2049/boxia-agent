"""P3-8 幂等与并发控制：Idempotency-Key 占位/重放/接管重试与 409 VERSION_CONFLICT。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import NotFoundError, ValidationError, VersionConflictError
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository
from internal.infrastructure.repository.apps.entitlement_request_log_repository import (
    EntitlementRequestLogRepository,
)

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
    code = f"idem-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"幂等租户{code}"})
    uow.commit()
    return t.id


def _service(uow: SqlAlchemyUnitOfWork) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="adminsystem")
    return EntitlementService(
        uow,
        EntitlementRepository(uow.session),
        context,
        request_log=EntitlementRequestLogRepository(uow.session),
    )


def _create_resource(uow: SqlAlchemyUnitOfWork, type_: str) -> object:
    rid = uow.resource_repo(type_).create({"name": f"{type_}幂等资源", "config": _CONFIG}).id
    uow.commit()
    return rid


def _apply(uow, tenant, items, key: str):
    return asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            items,
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
            idempotency_key=key,
        )
    )


def _log_row(uow, key: str):
    return EntitlementRequestLogRepository(uow.session).get(key)


def test_replay_returns_first_result_without_rewriting(uow, tenant):
    """同键重放返回首次结果；携带不同 items 也不产生新写入、不追加审计。"""
    skill_id = _create_resource(uow, "skill")
    other_id = _create_resource(uow, "skill")

    first = _apply(uow, tenant, [EntitlementItem("skill", skill_id)], "k-replay")
    assert first.updated == 1
    assert _log_row(uow, "k-replay")["status"] == "completed"

    replay = _apply(uow, tenant, [EntitlementItem("skill", other_id)], "k-replay")
    assert replay.updated == 1
    assert EntitlementRepository(uow.session).get(tenant, "skill", other_id) is None
    audits = uow.session.execute(
        text(
            "SELECT count(*) FROM audit_logs WHERE action = 'entitlement.batch' AND tenant_id = :t"
        ),
        {"t": tenant},
    ).scalar_one()
    assert audits == 1


def test_failed_details_replay_as_completed(uow, tenant):
    """业务失败明细（非异常）也是首次结果：completed 落库、重放原样返回。"""
    missing = uuid4()
    result = _apply(uow, tenant, [EntitlementItem("skill", missing)], "k-faildetail")
    assert result.updated == 0 and len(result.failed) == 1
    row = _log_row(uow, "k-faildetail")
    assert row["status"] == "completed"

    replay = _apply(uow, tenant, [EntitlementItem("skill", missing)], "k-faildetail")
    assert replay.failed[0]["object_id"] == str(missing)


def test_exception_marks_failed_and_retry_takeover(uow, tenant):
    """执行异常 → failed；同键重试接管（version+1）后成功 → completed。"""
    with pytest.raises(NotFoundError):
        _apply(uow, uuid4(), [EntitlementItem("skill", uuid4())], "k-retry")
    row = _log_row(uow, "k-retry")
    assert row["status"] == "failed" and row["version"] == 1

    skill_id = _create_resource(uow, "skill")
    result = _apply(uow, tenant, [EntitlementItem("skill", skill_id)], "k-retry")
    assert result.updated == 1
    row = _log_row(uow, "k-retry")
    assert row["status"] == "completed" and row["version"] == 2


def test_processing_conflict_returns_409(uow, tenant):
    """占位 processing 未决时并发同键 409 VERSION_CONFLICT，行保持 processing。"""
    key = f"k-proc-{uuid4().hex[:8]}"
    assert EntitlementRequestLogRepository(uow.session).try_begin(
        key, tenant, "batch", {"tenant_id": str(tenant), "mode": "grant", "items": []}
    )
    uow.commit()
    skill_id = _create_resource(uow, "skill")
    with pytest.raises(VersionConflictError, match="执行中"):
        _apply(uow, tenant, [EntitlementItem("skill", skill_id)], key)
    assert _log_row(uow, key)["status"] == "processing"
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is None


def test_key_validation_and_blank_ignored(uow, tenant):
    """超 128 字符 422；空/纯空白键视同未携带，不写去重行。"""
    skill_id = _create_resource(uow, "skill")
    with pytest.raises(ValidationError, match="128"):
        _apply(uow, tenant, [EntitlementItem("skill", skill_id)], "x" * 129)
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is None

    result = _apply(uow, tenant, [EntitlementItem("skill", skill_id)], "   ")
    assert result.updated == 1
    assert _log_row(uow, "   ") is None
