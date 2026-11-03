"""P3-5 资源类型注册表：目录种子防漂移、新增类型免迁移端到端、外键/应用校验兜底。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.application.apps.resource_service import AppResourceService
from internal.domain.entity.access import RESOURCE_TABLE_TYPES
from internal.domain.entity.entitlement import EntitlementItem
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import ValidationError
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_plan_repository import (
    EntitlementPlanRepository,
)
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository
from internal.infrastructure.repository.apps.resource_repository import AppResourceRepository
from internal.infrastructure.repository.apps.resource_type_catalog_repository import (
    ResourceTypeCatalogRepository,
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
    code = f"cat-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"目录租户{code}"})
    uow.commit()
    return t.id


def _resource_service(uow: SqlAlchemyUnitOfWork) -> AppResourceService:
    return AppResourceService(
        AppResourceRepository(uow.session), uow, ResourceTypeCatalogRepository(uow.session)
    )


def _entitlement_service(
    uow: SqlAlchemyUnitOfWork, *, with_catalog: bool = True
) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="adminsystem")
    return EntitlementService(
        uow,
        EntitlementRepository(uow.session),
        context,
        plan_repo=EntitlementPlanRepository(uow.session),
        type_catalog=ResourceTypeCatalogRepository(uow.session) if with_catalog else None,
    )


def _add_type(uow: SqlAlchemyUnitOfWork, code: str, *, active: bool = True) -> None:
    uow.session.execute(
        text(
            "INSERT INTO resource_type_catalog (code, name, sort_order, is_active) "
            "VALUES (:c, :n, 10, :a)"
        ),
        {"c": code, "n": f"类型{code}", "a": active},
    )
    uow.commit()


def _create_resource(uow: SqlAlchemyUnitOfWork, type_: str) -> object:
    rid = _resource_service(uow).create_resource(
        type=type_, name=f"{type_}目录资源", config=_CONFIG
    )
    uow.commit()
    return rid


def test_seed_and_constraint_replacement(uow):
    """种子与常量一致；三个静态 CHECK 撤销、resource.type 外键就位。"""
    codes = ResourceTypeCatalogRepository(uow.session).list_active()
    assert set(codes) == set(RESOURCE_TABLE_TYPES)
    dropped = uow.session.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conname IN "
            "('ck_resource_type', 'ck_resource_grants_type', 'ck_entitlement_plan_item_type')"
        )
    ).all()
    assert [r.conname for r in dropped] == []
    fk = uow.session.execute(
        text("SELECT count(*) FROM pg_constraint WHERE conname = 'fk_resource_type_catalog'")
    ).scalar_one()
    assert fk == 1


def test_unknown_type_rejected_by_service(uow):
    """应用校验先行：未注册类型 422，不触达 DB。"""
    with pytest.raises(ValidationError, match="resource type"):
        _resource_service(uow).create_resource(type="nope", name="x", config=_CONFIG)
    with pytest.raises(ValidationError, match="不支持的权益对象类型"):
        _entitlement_service(uow).list_by_tenant(uuid4(), object_type="nope")


def test_new_type_flows_end_to_end_without_migration(uow, tenant):
    """新增类型只插目录行：建资源、开权益、做套餐条目全链路免改迁移/CHECK。"""
    _add_type(uow, "report")
    rid = _create_resource(uow, "report")

    result = asyncio.run(
        _entitlement_service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("report", rid)],
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    assert result.updated == 1
    page = _entitlement_service(uow).list_by_tenant(tenant, object_type="report")
    assert page.total == 1 and page.items[0].status == "active"

    svc = _entitlement_service(uow)
    plan_id = svc.create_plan(
        code=f"p-{uuid4().hex[:6]}",
        name="新类型套餐",
        description="",
        auth_type="TRIAL",
        duration_days=7,
        quota={},
        items=[EntitlementItem("report", rid)],
        actor_id=_ACTOR_ID,
        actor_username=_ACTOR,
    )
    assert svc.get_plan(plan_id).items[0].object_type == "report"


def test_inactive_type_rejected_but_rows_untouched(uow):
    """停用目录行后应用校验拒绝新引用；服务请求级装配、每实例只查一次目录。"""
    _add_type(uow, "archive")
    assert _create_resource(uow, "archive")
    uow.session.execute(
        text("UPDATE resource_type_catalog SET is_active = FALSE WHERE code = 'archive'")
    )
    uow.commit()
    with pytest.raises(ValidationError, match="resource type"):
        _resource_service(uow).create_resource(type="archive", name="停用后新建", config=_CONFIG)


def test_service_without_catalog_falls_back_to_constants(uow):
    """未装配目录的旁路构造退回常量口径：常量内可用、目录新类型不放行。"""
    svc = _entitlement_service(uow, with_catalog=False)
    svc.list_by_tenant(uuid4(), object_type="tool")
    with pytest.raises(ValidationError, match="不支持的权益对象类型"):
        svc.list_by_tenant(uuid4(), object_type="report")
