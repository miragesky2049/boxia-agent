"""0057 subject_type 显式化校验：写路径回填、作用域 CHECK、部分唯一索引与 on_conflict 谓词对齐。"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.postgres_resource_grant_repository import (
    PostgresResourceGrantRepository,
)

_TOOL_CONFIG = {"url": "https://example.com/api", "method": "GET"}


@pytest.fixture()
def env():
    """准备 skill 资源、租户及其角色、平台角色；库由 conftest 会话级重建+清表。"""
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    try:
        resource_id: UUID = (
            uow.resource_repo("skill")
            .create({"name": "subject用例资源", "config": _TOOL_CONFIG})
            .id
        )
        code = f"subj-{uuid4().hex[:8]}"
        tenant = uow.tenants.create({"code": code, "name": f"租户{code}"})
        role = uow.roles.create(
            {
                "tenant_id": tenant.id,
                "code": "viewer",
                "name": f"只读-{code}",
                "description": "0057 用例",
                "is_system": False,
            }
        )
        platform_role_id: UUID = uow.session.execute(
            text("SELECT id FROM roles WHERE tenant_id = :pid LIMIT 1"),
            {"pid": PLATFORM_TENANT_ID},
        ).scalar_one()
        uow.commit()
        yield uow, resource_id, tenant.id, role.id, platform_role_id
    finally:
        uow.close()


def _insert_grant(uow: SqlAlchemyUnitOfWork, **fields) -> None:
    uow.session.execute(
        text(
            "INSERT INTO resource_grants (id, resource_type, resource_id, tenant_id, role_id, subject_type) "
            "VALUES (gen_random_uuid(), :rtype, :rid, :tid, :role_id, :subject_type)"
        ),
        {
            "rtype": "skill",
            "rid": fields["resource_id"],
            "tid": fields["tenant_id"],
            "role_id": fields.get("role_id"),
            "subject_type": fields["subject_type"],
        },
    )


def test_repo_writes_backfill_subject_type(env):
    """整租户写 'tenant'、按角色写 'role'，读回实体携带 subject_type。"""
    uow, resource_id, tenant_id, role_id, _ = env
    repo = PostgresResourceGrantRepository(uow.session)

    repo.replace_for_tenant("skill", resource_id, tenant_id, None, granted_by=None)
    uow.commit()
    row = uow.session.execute(
        text(
            "SELECT subject_type, role_id FROM resource_grants "
            "WHERE resource_id = :rid AND tenant_id = :tid"
        ),
        {"rid": resource_id, "tid": tenant_id},
    ).first()
    assert (row.subject_type, row.role_id) == ("tenant", None)
    grants = repo.list_for_resource("skill", resource_id, tenant_id)
    assert [g.subject_type for g in grants] == ["tenant"]

    repo.replace_for_role(role_id, tenant_id, "skill", [resource_id], granted_by=None)
    uow.commit()
    row = uow.session.execute(
        text("SELECT subject_type FROM resource_grants WHERE role_id = :rid"),
        {"rid": role_id},
    ).first()
    assert row.subject_type == "role"


def test_tenant_wide_duplicate_hits_subject_index(env):
    """同资源同租户两条 tenant → ux_resource_grants_tenant_subject 冲突。"""
    uow, resource_id, tenant_id, _, _ = env
    _insert_grant(uow, resource_id=resource_id, tenant_id=tenant_id, subject_type="tenant")
    with pytest.raises(IntegrityError, match="ux_resource_grants_tenant_subject"):
        _insert_grant(uow, resource_id=resource_id, tenant_id=tenant_id, subject_type="tenant")
    uow.session.rollback()


def test_role_duplicate_hits_subject_index(env):
    """同资源同租户同角色两条 role → ux_resource_grants_role_subject 冲突。"""
    uow, resource_id, tenant_id, role_id, _ = env
    _insert_grant(
        uow, resource_id=resource_id, tenant_id=tenant_id, role_id=role_id, subject_type="role"
    )
    with pytest.raises(IntegrityError, match="ux_resource_grants_role_subject"):
        _insert_grant(
            uow, resource_id=resource_id, tenant_id=tenant_id, role_id=role_id, subject_type="role"
        )
    uow.session.rollback()


def test_subject_check_rejects_mismatch(env):
    """tenant 档带 role_id、role 档缺 role_id 均违反 ck_resource_grants_subject。"""
    uow, resource_id, tenant_id, role_id, _ = env
    with pytest.raises(IntegrityError, match="ck_resource_grants_subject"):
        _insert_grant(
            uow,
            resource_id=resource_id,
            tenant_id=tenant_id,
            role_id=role_id,
            subject_type="tenant",
        )
    uow.session.rollback()
    with pytest.raises(IntegrityError, match="ck_resource_grants_subject"):
        _insert_grant(uow, resource_id=resource_id, tenant_id=tenant_id, subject_type="role")
    uow.session.rollback()


def test_add_for_role_on_conflict_matches_new_index(env):
    """add_for_role 的 index_where 必须匹配 ux_resource_grants_role_subject，重复授权静默跳过。"""
    uow, resource_id, tenant_id, role_id, _ = env
    repo = PostgresResourceGrantRepository(uow.session)
    assert repo.add_for_role(role_id, tenant_id, "skill", [resource_id], granted_by=None) == 1
    uow.commit()
    assert repo.add_for_role(role_id, tenant_id, "skill", [resource_id], granted_by=None) == 0
    uow.commit()


def test_add_for_platform_role_on_conflict_matches_new_index(env):
    """index_where 若与 ux_resource_grants_platform_role_subject 谓词不一致会直接 ProgrammingError。"""
    uow, resource_id, _, _, platform_role_id = env
    repo = PostgresResourceGrantRepository(uow.session)
    assert (
        repo.add_for_platform_role(platform_role_id, "skill", [resource_id], granted_by=None) == 1
    )
    uow.commit()
    assert (
        repo.add_for_platform_role(platform_role_id, "skill", [resource_id], granted_by=None) == 0
    )
    uow.commit()
