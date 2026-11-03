"""P3-3 套餐模板：创建校验、删除级联、apply_plan 复用批量语义（默认 auth_type/期限/配额）。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import NotFoundError, ValidationError
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_plan_repository import (
    EntitlementPlanRepository,
)
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
    code = f"plan-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"套餐租户{code}"})
    uow.commit()
    return t.id


def _service(uow: SqlAlchemyUnitOfWork) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="adminsystem")
    return EntitlementService(
        uow,
        EntitlementRepository(uow.session),
        context,
        plan_repo=EntitlementPlanRepository(uow.session),
    )


def _create_resource(uow: SqlAlchemyUnitOfWork, type_: str, name: str = "套餐资源") -> object:
    rid = uow.resource_repo(type_).create({"name": name, "config": _CONFIG}).id
    uow.commit()
    return rid


def _create_plan(uow, *, code=None, items, duration_days=30, auth_type="TRIAL"):
    return _service(uow).create_plan(
        code=code or f"plan-{uuid4().hex[:8]}",
        name="标准套餐",
        description="P3-3 用例",
        auth_type=auth_type,
        duration_days=duration_days,
        quota={"seat": 5},
        items=items,
        actor_id=_ACTOR_ID,
        actor_username=_ACTOR,
    )


def test_create_plan_validation_gates(uow, tenant):
    """code 唯一、条目非空且不重复、对象存在、期限为正：非法输入均拒绝且不落库。"""
    skill_id = _create_resource(uow, "skill")
    plan_id = _create_plan(uow, items=[EntitlementItem("skill", skill_id)])
    plan = _service(uow).get_plan(plan_id)
    assert plan.name == "标准套餐" and plan.duration_days == 30

    with pytest.raises(ValidationError, match="已存在"):
        _create_plan(uow, code=plan.code, items=[EntitlementItem("skill", skill_id)])
    with pytest.raises(ValidationError, match="条目不能为空"):
        _create_plan(uow, items=[])
    with pytest.raises(ValidationError, match="条目重复"):
        _create_plan(
            uow, items=[EntitlementItem("skill", skill_id), EntitlementItem("skill", skill_id)]
        )
    with pytest.raises(ValidationError, match="对象不存在"):
        _create_plan(uow, items=[EntitlementItem("skill", uuid4())])
    with pytest.raises(ValidationError, match="正数"):
        _create_plan(uow, items=[EntitlementItem("skill", skill_id)], duration_days=0)


def test_apply_plan_uses_template_defaults(uow, tenant):
    """开通展开条目：auth_type/quota 取模板默认，expire 按 duration_days 顺延，reason 兜底套餐名。"""
    now = datetime.now(UTC)
    skill_id = _create_resource(uow, "skill")
    tool_id = _create_resource(uow, "tool")
    plan_id = _create_plan(
        uow,
        items=[EntitlementItem("skill", skill_id), EntitlementItem("tool", tool_id)],
        duration_days=30,
    )

    result = asyncio.run(
        _service(uow).apply_plan(tenant, plan_id, actor_id=_ACTOR_ID, actor_username=_ACTOR)
    )
    assert result.updated == 2 and result.failed == ()

    repo = EntitlementRepository(uow.session)
    view = repo.get(tenant, "skill", skill_id)
    assert view.auth_type == "TRIAL"
    assert view.quota == {"seat": 5}
    assert view.remark == "套餐开通：标准套餐"
    delta = view.expire_time - now
    assert timedelta(days=29) < delta < timedelta(days=31)


def test_apply_plan_start_time_and_explicit_expire(uow, tenant):
    """start_time 顺延到期点；显式 expire_time 覆盖模板期限；未到点持久态 wait_effect。"""
    now = datetime.now(UTC)
    skill_id = _create_resource(uow, "skill")
    plan_id = _create_plan(uow, items=[EntitlementItem("skill", skill_id)], duration_days=30)
    start = now + timedelta(days=2)
    explicit_expire = now + timedelta(days=9)

    result = asyncio.run(
        _service(uow).apply_plan(
            tenant,
            plan_id,
            start_time=start,
            expire_time=explicit_expire,
            reason="续约",
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    assert result.updated == 1
    raw = uow.session.execute(
        text(
            "SELECT status, expire_time, remark FROM tenant_resource_entitlement WHERE resource_id = :rid"
        ),
        {"rid": skill_id},
    ).first()
    assert raw.status == "wait_effect"
    assert raw.expire_time == explicit_expire
    assert raw.remark == "续约"


def test_apply_plan_deprecated_item_fails_atomically(uow, tenant):
    """模板内弃用对象：apply_batch 整体拒绝，failed 明细返回，无任何权益落库。"""
    skill_id = _create_resource(uow, "skill")
    tool_id = _create_resource(uow, "tool")
    plan_id = _create_plan(
        uow, items=[EntitlementItem("skill", skill_id), EntitlementItem("tool", tool_id)]
    )
    uow.session.execute(
        text("UPDATE resource SET is_deprecated = TRUE WHERE id = :rid"), {"rid": tool_id}
    )
    uow.commit()

    result = asyncio.run(
        _service(uow).apply_plan(tenant, plan_id, actor_id=_ACTOR_ID, actor_username=_ACTOR)
    )
    assert result.updated == 0
    assert "弃用" in result.failed[0]["reason"]
    repo = EntitlementRepository(uow.session)
    assert repo.get(tenant, "skill", skill_id) is None
    assert repo.get(tenant, "tool", tool_id) is None


def test_delete_plan_cascades_items_keeps_entitlements(uow, tenant):
    """删除模板仅清定义与条目行（外键级联），已开通权益保持；缺失/重复删除 404。"""
    skill_id = _create_resource(uow, "skill")
    plan_id = _create_plan(uow, items=[EntitlementItem("skill", skill_id)])
    asyncio.run(
        _service(uow).apply_plan(tenant, plan_id, actor_id=_ACTOR_ID, actor_username=_ACTOR)
    )

    _service(uow).delete_plan(plan_id, actor_id=_ACTOR_ID, actor_username=_ACTOR)

    assert EntitlementPlanRepository(uow.session).get(plan_id) is None
    items_left = uow.session.execute(
        text("SELECT count(*) FROM entitlement_plan_item WHERE plan_id = :pid"), {"pid": plan_id}
    ).scalar_one()
    assert items_left == 0
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is not None

    with pytest.raises(NotFoundError):
        _service(uow).delete_plan(plan_id, actor_id=_ACTOR_ID, actor_username=_ACTOR)
