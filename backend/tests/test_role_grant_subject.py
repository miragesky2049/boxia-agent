"""角色授权读侧 subject_type 显式语义（P1-10）：两档可见性、整租户判定、新角色继承与增删联动。"""

from uuid import UUID, uuid4

from internal.application.role_grant_service import RoleGrantService
from internal.domain.entity.request_context import TENANT_SCOPE, RequestContext
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.resource_tool_repository import ResourceToolRepository

_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


def _visible_ids(
    uow: SqlAlchemyUnitOfWork,
    tenant_id: UUID,
    role_ids: tuple[UUID, ...],
    apply_role_filter: bool = True,
) -> set[UUID]:
    repo = ResourceToolRepository(uow.session, tenant_id, role_ids, apply_role_filter, "tool")
    items, _ = repo.list_page(1, 100, None, None)
    return {item.id for item in items}


def _create_env() -> dict[str, UUID]:
    """租户 + viewer/admin 两个启用角色 + old 停用角色；两个租户自有工具（role 档 / tenant 档）。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        code = f"subj10-{uuid4().hex[:8]}"
        tenant = uow.tenants.create({"code": code, "name": f"租户{code}"})
        roles = {}
        for role_code, name in (("viewer", "只读"), ("admin", "管理"), ("old", "停用")):
            roles[role_code] = uow.roles.create(
                {
                    "tenant_id": tenant.id,
                    "code": role_code,
                    "name": f"{name}-{code}",
                    "description": "P1-10 用例",
                    "is_system": False,
                }
            )
        scoped = ResourceToolRepository(uow.session, tenant.id, (), True, "tool")
        tool_role = scoped.create({"name": "角色档工具", "config": _TOOL_CONFIG}).id
        tool_wide = scoped.create({"name": "整租户工具", "config": _TOOL_CONFIG}).id
        uow.resource_grants.add_for_role(roles["viewer"].id, tenant.id, "tool", [tool_role], None)
        uow.resource_grants.set_tenant_wide("tool", tool_wide, tenant.id, None)
        uow.roles.update(roles["old"].id, {"is_active": False})
        uow.commit()
        return {
            "tenant": tenant.id,
            "viewer": roles["viewer"].id,
            "admin": roles["admin"].id,
            "old": roles["old"].id,
            "tool_role": tool_role,
            "tool_wide": tool_wide,
        }
    finally:
        uow.close()


def test_visibility_matrix_tenant_tier_vs_role_tier() -> None:
    env = _create_env()
    tenant, viewer, admin = env["tenant"], env["viewer"], env["admin"]
    both = {env["tool_role"], env["tool_wide"]}
    scoped = SqlAlchemyUnitOfWork()
    # tenant 档对任意角色（含空角色集合）可见；role 档只对指定角色可见
    assert _visible_ids(scoped, tenant, ()) == {env["tool_wide"]}
    assert _visible_ids(scoped, tenant, (admin,)) == {env["tool_wide"]}
    assert _visible_ids(scoped, tenant, (viewer,)) == both
    # 关闭角色过滤时两档均可见
    assert _visible_ids(scoped, tenant, (admin,), apply_role_filter=False) == both
    scoped.close()


def test_tenant_wide_reads_only_recognize_tenant_tier() -> None:
    env = _create_env()
    uow = SqlAlchemyUnitOfWork()
    grants = uow.resource_grants
    assert grants.list_tenant_wide_resource_ids(env["tenant"], "tool") == {env["tool_wide"]}
    assert grants.has_tenant_wide("tool", env["tool_wide"], env["tenant"])
    assert not grants.has_tenant_wide("tool", env["tool_role"], env["tenant"])
    assert grants.list_effective_granted_resource_ids(env["viewer"], env["tenant"], "tool") == {
        env["tool_role"],
        env["tool_wide"],
    }
    assert grants.list_effective_granted_resource_ids(env["admin"], env["tenant"], "tool") == {
        env["tool_wide"]
    }
    assert grants.count_effective_granted(env["viewer"], env["tenant"], "tool") == 2
    uow.close()


def test_new_role_inherits_tenant_tier() -> None:
    env = _create_env()
    uow = SqlAlchemyUnitOfWork()
    late = uow.roles.create(
        {
            "tenant_id": env["tenant"],
            "code": "late",
            "name": "新建角色",
            "description": "P1-10 继承用例",
            "is_system": False,
        }
    )
    uow.commit()
    # tenant 档资源自动对新建角色生效，无需补写授权
    assert uow.resource_grants.list_effective_granted_resource_ids(
        late.id, env["tenant"], "tool"
    ) == {env["tool_wide"]}
    assert {env["tool_wide"]} <= _visible_ids(uow, env["tenant"], (late.id,))
    uow.close()


def test_set_tenant_wide_supersedes_role_rows_idempotent() -> None:
    env = _create_env()
    uow = SqlAlchemyUnitOfWork()
    grants = uow.resource_grants
    assert grants.add_for_role(env["admin"], env["tenant"], "tool", [env["tool_wide"]], None) == 1
    uow.commit()
    grants.set_tenant_wide("tool", env["tool_wide"], env["tenant"], None)
    grants.set_tenant_wide("tool", env["tool_wide"], env["tenant"], None)
    uow.commit()
    # set_tenant_wide 清除同资源 role 档行且幂等保留唯一 tenant 档行
    assert grants.list_for_role(env["admin"], "tool") == []
    assert grants.has_tenant_wide("tool", env["tool_wide"], env["tenant"])
    # 其他资源的 role 档不受影响
    assert grants.list_effective_granted_resource_ids(env["viewer"], env["tenant"], "tool") == {
        env["tool_role"],
        env["tool_wide"],
    }
    uow.close()


def test_service_add_skips_tenant_wide_and_remove_demotes_active_roles() -> None:
    env = _create_env()
    uow = SqlAlchemyUnitOfWork(tenant_id=env["tenant"])
    try:
        tenant = uow.tenants.get_by_id(env["tenant"])
        assert tenant is not None
        context = RequestContext(scope=TENANT_SCOPE, tenant=tenant, host="t.local")
        service = RoleGrantService(uow, context)

        added = service.add(
            env["viewer"], "tool", [env["tool_wide"]], actor_id=env["admin"], actor_username="svc"
        )
        assert added == 0

        # 整租户去权：tenant 档删除，其余启用角色补 role 档；停用角色与目标角色不保留
        service.remove(
            env["viewer"], "tool", env["tool_wide"], actor_id=env["admin"], actor_username="svc"
        )
        grants = uow.resource_grants
        assert not grants.has_tenant_wide("tool", env["tool_wide"], env["tenant"])
        assert env["tool_wide"] in grants.list_effective_granted_resource_ids(
            env["admin"], env["tenant"], "tool"
        )
        assert grants.list_effective_granted_resource_ids(env["viewer"], env["tenant"], "tool") == {
            env["tool_role"]
        }
        assert (
            grants.list_effective_granted_resource_ids(env["old"], env["tenant"], "tool") == set()
        )
    finally:
        uow.close()
