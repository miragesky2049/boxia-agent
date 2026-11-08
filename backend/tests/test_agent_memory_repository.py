"""M4 PRD F16.2：agent_memory 仓储单测（真实 PG，裸 SQL 口径对齐会话仓储）。

覆盖：增查删、活跃过滤与时近排序、容量 FIFO 归档、合并改写（仅活跃）、
作用域删除防 IDOR、命中计数、run 幂等探测、kind CHECK 约束。
user_id 无外键（PRD F16.2），测试可用随机 UUID。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.agent_memory_repository import AgentMemoryRepository


@pytest.fixture()
def uow():
    unit = SqlAlchemyUnitOfWork()
    unit.apply_scope((), apply_role_filter=False)
    try:
        yield unit
    finally:
        unit.close()


@pytest.fixture()
def scope(uow):
    """造 tenant×app 作用域（记忆表外键要求），返回 (tenant_id, app_id, user_id)。"""
    code = f"mem-{uuid4().hex[:8]}"
    tenant = uow.tenants.create({"code": code, "name": f"记忆租户{code}"})
    app_id = uuid4()
    uow.session.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '记忆应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": app_id},
    )
    uow.commit()
    return tenant.id, app_id, uuid4()


def _repo(uow) -> AgentMemoryRepository:
    return AgentMemoryRepository(uow.session)


def _insert(uow, scope, content: str, **kwargs):
    tenant_id, app_id, user_id = scope
    repo = _repo(uow)
    memory_id = repo.insert(
        tenant_id=tenant_id,
        application_id=app_id,
        user_id=user_id,
        content=content,
        **kwargs,
    )
    uow.commit()
    return memory_id


def _set_created(uow, memory_id, minutes_ago: int) -> None:
    """PG 同事务 now() 相同，FIFO 用例需显式拉开 created_at/updated_at。"""
    stamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    uow.session.execute(
        text("UPDATE agent_memory SET created_at = :ts, updated_at = :ts WHERE id = :id"),
        {"ts": stamp, "id": memory_id},
    )
    uow.commit()


def _kind(kind: str = "fact"):
    return {"kind": kind}


def test_insert_get_roundtrip_with_defaults(uow, scope) -> None:
    row = _repo(uow).get(_insert(uow, scope, "用户偏好简洁回复", **_kind()))
    assert row is not None
    assert row["kind"] == "fact"
    assert row["status"] == "active"
    assert row["hit_count"] == 0
    assert row["source_run_id"] is None
    assert row["metadata"] == {}


def test_insert_persists_metadata_and_source_run(uow, scope) -> None:
    run_id = uuid4()
    memory_id = _insert(
        uow,
        scope,
        "住在杭州",
        kind="preference",
        source_run_id=run_id,
        metadata={"from": "chat"},
    )
    row = _repo(uow).get(memory_id)
    assert row["metadata"] == {"from": "chat"}
    assert row["source_run_id"] == run_id


def test_kind_check_constraint_rejects_unknown(uow, scope) -> None:
    with pytest.raises(IntegrityError):
        _insert(uow, scope, "非法种类", kind="note")
    uow.rollback()


def test_list_active_filters_status_and_orders_by_recency(uow, scope) -> None:
    old = _insert(uow, scope, "旧记忆", **_kind())
    _set_created(uow, old, minutes_ago=30)
    new = _insert(uow, scope, "新记忆", **_kind())
    _set_created(uow, new, minutes_ago=5)
    _repo(uow).archive_overflow(
        tenant_id=scope[0], application_id=scope[1], user_id=scope[2], max_active=1
    )
    uow.commit()
    rows = _repo(uow).list_active(tenant_id=scope[0], application_id=scope[1], user_id=scope[2])
    assert [r["content"] for r in rows] == ["新记忆"]


def test_list_active_respects_limit_and_scope_isolation(uow, scope) -> None:
    for index in range(3):
        _insert(uow, scope, f"记忆{index}", **_kind())
    tenant_id, app_id, user_id = scope
    repo = _repo(uow)
    assert (
        len(repo.list_active(tenant_id=tenant_id, application_id=app_id, user_id=user_id, limit=2))
        == 2
    )
    assert repo.list_active(tenant_id=tenant_id, application_id=app_id, user_id=uuid4()) == []


def test_count_and_archive_overflow_fifos_oldest(uow, scope) -> None:
    repo = _repo(uow)
    ids = [_insert(uow, scope, f"记忆{i}", **_kind()) for i in range(5)]
    for index, memory_id in enumerate(ids):
        _set_created(uow, memory_id, minutes_ago=100 - index)
    assert repo.count_active(tenant_id=scope[0], application_id=scope[1], user_id=scope[2]) == 5
    archived = repo.archive_overflow(
        tenant_id=scope[0], application_id=scope[1], user_id=scope[2], max_active=3
    )
    uow.commit()
    assert archived == 2
    assert repo.get(ids[0])["status"] == "archived"
    assert repo.get(ids[1])["status"] == "archived"
    assert repo.get(ids[4])["status"] == "active"
    # 未超限再收口：0 行
    assert (
        repo.archive_overflow(
            tenant_id=scope[0], application_id=scope[1], user_id=scope[2], max_active=3
        )
        == 0
    )


def test_update_content_only_touches_active(uow, scope) -> None:
    repo = _repo(uow)
    active = _insert(uow, scope, "原内容", **_kind())
    assert repo.update_content(active, content="新内容", kind="episode") is True
    row = repo.get(active)
    assert row["content"] == "新内容" and row["kind"] == "episode"
    repo.archive_overflow(
        tenant_id=scope[0], application_id=scope[1], user_id=scope[2], max_active=0
    )
    uow.commit()
    assert repo.update_content(active, content="不应生效") is False
    assert repo.update_content(uuid4(), content="不存在") is False


def test_delete_scoped_blocks_cross_tenant(uow, scope) -> None:
    repo = _repo(uow)
    memory_id = _insert(uow, scope, "待删除", **_kind())
    assert repo.delete_scoped(memory_id, tenant_id=uuid4(), user_id=scope[2]) is False
    assert repo.delete_scoped(memory_id, tenant_id=scope[0], user_id=uuid4()) is False
    uow.commit()
    assert repo.delete_scoped(memory_id, tenant_id=scope[0], user_id=scope[2]) is True
    uow.commit()
    assert repo.get(memory_id) is None


def test_delete_by_scope_clears_all_statuses(uow, scope) -> None:
    repo = _repo(uow)
    _insert(uow, scope, "活跃1", **_kind())
    archived = _insert(uow, scope, "将被归档", **_kind())
    repo.archive_overflow(
        tenant_id=scope[0], application_id=scope[1], user_id=scope[2], max_active=0
    )
    uow.commit()
    deleted = repo.delete_by_scope(tenant_id=scope[0], application_id=scope[1], user_id=scope[2])
    uow.commit()
    assert deleted == 2
    assert repo.get(archived) is None


def test_bump_hit_count_increments_without_touching_updated_at(uow, scope) -> None:
    repo = _repo(uow)
    memory_id = _insert(uow, scope, "被命中", **_kind())
    before = repo.get(memory_id)["updated_at"]
    assert repo.bump_hit_count([]) == 0
    assert repo.bump_hit_count([memory_id, uuid4()]) == 1
    uow.commit()
    row = repo.get(memory_id)
    assert row["hit_count"] == 1
    assert row["updated_at"] == before


def test_exists_by_source_run_idempotency_probe(uow, scope) -> None:
    repo = _repo(uow)
    run_id = uuid4()
    assert repo.exists_by_source_run(run_id) is False
    _insert(uow, scope, "本轮沉淀", kind="fact", source_run_id=run_id)
    assert repo.exists_by_source_run(run_id) is True
    assert repo.exists_by_source_run(uuid4()) is False
