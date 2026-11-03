"""P1-5 EntitlementService：统一读写两套存储的用例语义（批量原子/软失效/恢复/严格模式/弃用拦截）。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.entity.entitlement import (
    ENTITLEMENT_OBJECT_TYPES,
    EntitlementItem,
)
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import ForbiddenError, NotFoundError, ValidationError
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
    code = f"ent-{uuid4().hex[:8]}"
    t = uow.tenants.create({"code": code, "name": f"权益租户{code}"})
    uow.commit()
    return t.id


def _service(uow: SqlAlchemyUnitOfWork, *, revoke_strict: bool = False) -> EntitlementService:
    context = RequestContext(scope="platform", tenant=None, host="adminsystem")
    return EntitlementService(
        uow, EntitlementRepository(uow.session), context, revoke_strict=revoke_strict
    )


def _create_resource(uow: SqlAlchemyUnitOfWork, type_: str) -> object:
    rid = uow.resource_repo(type_).create({"name": f"{type_}用例资源", "config": _CONFIG}).id
    uow.commit()
    return rid


def _create_app(uow: SqlAlchemyUnitOfWork, tenant_id) -> object:
    app_id = ApplicationRepository(uow.session).create_application("权益应用", "tenant", tenant_id)
    uow.commit()
    return app_id


def _create_role_with_grant(uow: SqlAlchemyUnitOfWork, tenant_id, resource_id) -> str:
    code = uuid4().hex[:8]
    role_name = f"授权角色-{code}"
    role = uow.roles.create(
        {
            "tenant_id": tenant_id,
            "code": "custom",
            "name": role_name,
            "description": "P1-5 用例",
            "is_system": False,
        }
    )
    uow.commit()
    uow.resource_grants.replace_for_role(
        role.id, tenant_id, "skill", [resource_id], granted_by=None
    )
    uow.commit()
    return role_name


def _apply(uow: SqlAlchemyUnitOfWork, tenant_id, mode: str, items: list[EntitlementItem]):
    return asyncio.run(
        _service(uow).apply_batch(tenant_id, mode, items, actor_id=_ACTOR_ID, actor_username=_ACTOR)
    )


def test_grant_and_list_five_object_types(uow, tenant):
    """五类对象经同一服务开通并可分页查询/过滤/反查。"""
    app_id = _create_app(uow, tenant)
    ids = {t: _create_resource(uow, t) for t in ("tool", "skill", "prompt", "knowledge")}
    items = [EntitlementItem("app", app_id)] + [EntitlementItem(t, i) for t, i in ids.items()]

    result = _apply(uow, tenant, "grant", items)
    assert result.updated == 5 and result.failed == ()

    svc = _service(uow)
    page = svc.list_by_tenant(tenant)
    assert page.total == 5
    assert {v.object_type for v in page.items} == set(ENTITLEMENT_OBJECT_TYPES)
    assert all(v.status == "active" for v in page.items)
    assert {v.object_id for v in page.items if v.object_type == "app"} == {app_id}

    tool_page = svc.list_by_tenant(tenant, object_type="tool")
    assert [v.object_id for v in tool_page.items] == [ids["tool"]]
    app_page = svc.list_by_tenant(tenant, keyword="权益应用")
    assert app_page.total == 1 and app_page.items[0].object_type == "app"

    tenants_page = svc.list_tenants_by_object("skill", ids["skill"])
    assert tenants_page.total == 1
    assert tenants_page.items[0]["tenant_id"] == tenant
    assert tenants_page.items[0]["status"] == "active"


def test_preview_add_remove_unchanged(uow, tenant):
    """preview 三组分类：已 active 为 unchanged、无行为 add、revoke 附带角色授权影响面。"""
    skill_id = _create_resource(uow, "skill")
    _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])
    role_name = _create_role_with_grant(uow, tenant, skill_id)

    svc = _service(uow)
    prompt_id = _create_resource(uow, "prompt")
    p = svc.preview(
        tenant, "grant", [EntitlementItem("skill", skill_id), EntitlementItem("prompt", prompt_id)]
    )
    assert [v.object_type for v in p.unchanged] == ["skill"]
    assert [v.object_type for v in p.add] == ["prompt"]
    assert p.remove == ()

    r = svc.preview(tenant, "revoke", [EntitlementItem("skill", skill_id)])
    assert len(r.remove) == 1
    assert r.remove[0].affected_role_grants == 1
    assert r.remove[0].affected_role_names == (role_name,)


def test_grant_revoke_restore_and_soft_semantics(uow, tenant):
    """grant→revoke→grant 恢复；软失效只置 revoked，不删 resource_grants 角色授权行。"""
    skill_id = _create_resource(uow, "skill")
    _create_role_with_grant(uow, tenant, skill_id)
    repo = EntitlementRepository(uow.session)

    assert _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)]).updated == 1
    assert repo.get(tenant, "skill", skill_id).status == "active"

    assert _apply(uow, tenant, "revoke", [EntitlementItem("skill", skill_id)]).updated == 1
    assert repo.get(tenant, "skill", skill_id).status == "revoked"
    kept = uow.session.execute(
        text("SELECT count(*) FROM resource_grants WHERE resource_id = :rid"),
        {"rid": skill_id},
    ).scalar_one()
    assert kept == 1

    assert _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)]).updated == 1
    assert repo.get(tenant, "skill", skill_id).status == "active"


def test_strict_mode_rejects_revoke(uow, tenant):
    """严格模式：角色授权仍引用权益时整批拒绝，权益保持 active。"""
    skill_id = _create_resource(uow, "skill")
    _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])
    _create_role_with_grant(uow, tenant, skill_id)

    svc = _service(uow, revoke_strict=True)
    with pytest.raises(ValidationError, match="严格模式"):
        asyncio.run(
            svc.apply_batch(
                tenant,
                "revoke",
                [EntitlementItem("skill", skill_id)],
                actor_id=_ACTOR_ID,
                actor_username=_ACTOR,
            )
        )
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id).status == "active"


def test_deprecated_resource_not_grantable(uow, tenant):
    """弃用资源不可新开通：failed 明细返回原因，不写入任何行。"""
    skill_id = _create_resource(uow, "skill")
    uow.session.execute(
        text("UPDATE resource SET is_deprecated = TRUE WHERE id = :rid"), {"rid": skill_id}
    )
    uow.commit()

    result = _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])
    assert result.updated == 0
    assert "弃用" in result.failed[0]["reason"]
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is None


def test_batch_size_and_mode_validation(uow, tenant):
    """空批/超限/非法模式均 422，且不触达写入。"""
    svc = _service(uow)
    with pytest.raises(ValidationError, match="不能为空"):
        asyncio.run(svc.apply_batch(tenant, "grant", [], actor_id=_ACTOR_ID, actor_username=_ACTOR))
    many = [EntitlementItem("skill", uuid4()) for _ in range(201)]
    with pytest.raises(ValidationError, match="不能超过"):
        asyncio.run(
            svc.apply_batch(tenant, "grant", many, actor_id=_ACTOR_ID, actor_username=_ACTOR)
        )
    with pytest.raises(ValidationError, match="批量模式"):
        asyncio.run(
            svc.apply_batch(
                tenant,
                "wipe",
                [EntitlementItem("skill", uuid4())],
                actor_id=_ACTOR_ID,
                actor_username=_ACTOR,
            )
        )


def test_tenant_missing_or_inactive(uow, tenant):
    """租户不存在 404；租户停用 422，写侧首先校验。"""
    svc = _service(uow)
    with pytest.raises(NotFoundError):
        asyncio.run(
            svc.apply_batch(
                uuid4(),
                "grant",
                [EntitlementItem("skill", uuid4())],
                actor_id=_ACTOR_ID,
                actor_username=_ACTOR,
            )
        )
    uow.session.execute(
        text("UPDATE tenants SET is_active = FALSE WHERE id = :tid"), {"tid": tenant}
    )
    uow.commit()
    with pytest.raises(ValidationError, match="停用"):
        asyncio.run(
            svc.apply_batch(
                tenant,
                "grant",
                [EntitlementItem("skill", uuid4())],
                actor_id=_ACTOR_ID,
                actor_username=_ACTOR,
            )
        )


def test_tenant_scope_forbidden(uow):
    """权益操作仅限平台作用域，租户上下文 403（SCOPE_FORBIDDEN 语义）。"""
    context = RequestContext(scope="tenant", tenant=None, host="t.local")
    svc = EntitlementService(uow, EntitlementRepository(uow.session), context)
    with pytest.raises(ForbiddenError):
        svc.list_by_tenant(uuid4())


def _purge(uow, tenant, object_type, object_id, *, role_code="superadmin", confirm=True):
    return asyncio.run(
        _service(uow).purge(
            tenant,
            object_type,
            object_id,
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
            actor_role_code=role_code,
            confirm=confirm,
            reason="用例清理",
        )
    )


def test_purge_deletes_entitlement_rows(uow, tenant):
    """purge 物理删权益行并连带删除支撑的角色授权行，先写含快照的审计（P3-6）。"""
    skill_id = _create_resource(uow, "skill")
    _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])
    _create_role_with_grant(uow, tenant, skill_id)

    result = _purge(uow, tenant, "skill", skill_id)
    assert result["deleted"] == 1
    assert result["role_grants_deleted"] == 1
    assert UUID(result["audit_id"])
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is None
    kept = uow.session.execute(
        text("SELECT count(*) FROM resource_grants WHERE resource_id = :rid"), {"rid": skill_id}
    ).scalar_one()
    assert kept == 0
    audit = uow.session.execute(
        text(
            "SELECT detail FROM audit_logs WHERE action = 'entitlement.purge' AND tenant_id = :tid "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"tid": tenant},
    ).first()
    assert audit is not None
    assert audit.detail["snapshot"]["object_id"] == str(skill_id)
    assert audit.detail["role_grants_before"][0]["role_name"].startswith("授权角色")


def test_purge_requires_superadmin_and_confirm(uow, tenant):
    """非 superadmin 403、未二次确认 422，均不删任何行。"""
    skill_id = _create_resource(uow, "skill")
    _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])

    with pytest.raises(ForbiddenError, match="superadmin"):
        _purge(uow, tenant, "skill", skill_id, role_code="admin")
    with pytest.raises(ValidationError, match="二次确认"):
        _purge(uow, tenant, "skill", skill_id, confirm=False)
    assert EntitlementRepository(uow.session).get(tenant, "skill", skill_id) is not None


def _raw_entitlement_status(uow: SqlAlchemyUnitOfWork, resource_id) -> str:
    row = uow.session.execute(
        text("SELECT status FROM tenant_resource_entitlement WHERE resource_id = :rid"),
        {"rid": resource_id},
    ).first()
    return row.status


def test_process_resource_wait_effective_flips_at_start_time(uow, tenant):
    """P3-1：未到 start_time 不动；到点后 wait_effect 行落库为 active。"""
    now = datetime.now(UTC)
    tool_id = _create_resource(uow, "tool")
    asyncio.run(
        _service(uow).apply_batch(
            tenant,
            "grant",
            [EntitlementItem("tool", tool_id)],
            start_time=now + timedelta(days=1),
            actor_id=_ACTOR_ID,
            actor_username=_ACTOR,
        )
    )
    assert _raw_entitlement_status(uow, tool_id) == "wait_effect"

    svc = _service(uow)
    assert svc.process_resource_wait_effective(now) == 0
    assert svc.process_resource_wait_effective(now + timedelta(days=2)) == 1
    assert _raw_entitlement_status(uow, tool_id) == "active"
    # 幂等：再次流转无行可动
    assert svc.process_resource_wait_effective(now + timedelta(days=2)) == 0


def test_process_resource_expired_flips_after_expire(uow, tenant):
    """P3-1：active 行过 expire_time 落库为 expired；revoked 行不受影响。"""
    now = datetime.now(UTC)
    tool_id = _create_resource(uow, "tool")
    skill_id = _create_resource(uow, "skill")
    _apply(uow, tenant, "grant", [EntitlementItem("tool", tool_id)])
    _apply(uow, tenant, "grant", [EntitlementItem("skill", skill_id)])
    _apply(uow, tenant, "revoke", [EntitlementItem("skill", skill_id)])
    for rid in (tool_id, skill_id):
        uow.session.execute(
            text(
                "UPDATE tenant_resource_entitlement SET expire_time = :t WHERE resource_id = :rid"
            ),
            {"t": now - timedelta(hours=1), "rid": rid},
        )
    uow.commit()

    svc = _service(uow)
    assert svc.process_resource_expired(now) == 1
    assert _raw_entitlement_status(uow, tool_id) == "expired"
    assert _raw_entitlement_status(uow, skill_id) == "revoked"
    assert svc.process_resource_expired(now) == 0
