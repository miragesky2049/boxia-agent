"""GrantService 仓储路由：五类资源各走对应仓储，overview/replace/replace_batch 不再一律按 tool。"""

from uuid import UUID, uuid4

import pytest

from internal.application.grant_service import GrantService
from internal.domain.entity.request_context import PLATFORM_SCOPE, RequestContext
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository

_RESOURCE_TYPES = ("app", "tool", "skill", "prompt", "knowledge")
_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


def _platform_uow() -> SqlAlchemyUnitOfWork:
    """平台超级管理员视角：关闭角色过滤，否则未授权平台资源不可见。"""
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def _platform_service(uow: SqlAlchemyUnitOfWork) -> GrantService:
    context = RequestContext(scope=PLATFORM_SCOPE, tenant=None, host="admin.local")
    return GrantService(uow, context)


def _create_resource(uow: SqlAlchemyUnitOfWork, resource_type: str) -> UUID:
    if resource_type == "app":
        app_id = ApplicationRepository(uow.session).create_application(
            name=f"授权应用-{resource_type}",
            owner_type="platform",
            owner_id=None,
            description="类型路由用例",
        )
        uow.commit()
        return app_id
    created = uow.resource_repo(resource_type).create(
        {"name": f"授权资源-{resource_type}", "config": _TOOL_CONFIG}
    )
    uow.commit()
    return created.id


def _create_tenant_role(uow: SqlAlchemyUnitOfWork, code: str) -> tuple[UUID, UUID]:
    tenant = uow.tenants.create({"code": code, "name": f"租户{code}"})
    role = uow.roles.create(
        {
            "tenant_id": tenant.id,
            "code": "viewer",
            "name": f"只读-{code}",
            "description": "类型路由用例",
            "is_system": False,
        }
    )
    uow.commit()
    return tenant.id, role.id


@pytest.mark.parametrize("resource_type", _RESOURCE_TYPES)
def test_overview_replace_and_batch_per_type(resource_type: str):
    uow = _platform_uow()
    try:
        service = _platform_service(uow)
        resource_id = _create_resource(uow, resource_type)
        tenant_id, role_id = _create_tenant_role(uow, f"gr-{resource_type}")

        page = service.overview(resource_type, 1, 50, None, None)
        assert resource_id in {item.resource_id for item in page.items}

        grants = service.replace(
            resource_type,
            resource_id,
            [(tenant_id, role_id)],
            actor_id=uuid4(),
            actor_username="tester",
        )
        assert {(g.tenant_id, g.role_id) for g in grants} == {(tenant_id, role_id)}
        read_back = service.list_grants(resource_type, resource_id, tenant_id)
        assert {(g.tenant_id, g.role_id) for g in read_back} == {(tenant_id, role_id)}

        service.replace(resource_type, resource_id, [], actor_id=uuid4(), actor_username="tester")
        assert service.list_grants(resource_type, resource_id, tenant_id) == []

        processed = service.replace_batch(
            resource_type,
            [resource_id],
            mode="replace",
            tenant_id=tenant_id,
            role_ids=[role_id],
            actor_id=uuid4(),
            actor_username="tester",
        )
        assert processed == 1
        after_batch = service.list_grants(resource_type, resource_id, tenant_id)
        assert {(g.tenant_id, g.role_id) for g in after_batch} == {(tenant_id, role_id)}
    finally:
        uow.close()


def test_overview_does_not_leak_across_types():
    """skill 的授权总览不得返回 tool，反之亦然（修复前两类都查 tools 仓储）。"""
    uow = _platform_uow()
    try:
        service = _platform_service(uow)
        tool_id = _create_resource(uow, "tool")
        skill_id = _create_resource(uow, "skill")
        skill_ids = {
            item.resource_id for item in service.overview("skill", 1, 50, None, None).items
        }
        tool_ids = {item.resource_id for item in service.overview("tool", 1, 50, None, None).items}
        assert skill_id in skill_ids and tool_id not in skill_ids
        assert tool_id in tool_ids and skill_id not in tool_ids
    finally:
        uow.close()


def test_invalid_resource_type_rejected():
    uow = _platform_uow()
    try:
        from internal.application.errors import ValidationError

        with pytest.raises(ValidationError):
            _platform_service(uow).overview("component", 1, 10, None, None)
    finally:
        uow.close()
