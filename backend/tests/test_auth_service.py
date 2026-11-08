"""AuthService + GrantService 单元测试（内存实现，不连数据库）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from internal.domain.auth import (
    AuthCache,
    AuthService,
    CreateGrantRequest,
    GrantError,
    GrantService,
)
from internal.domain.entity.auth_constants import AuthType


class InMemoryAuthCache(AuthCache):
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.store.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class FakeAuthRepo:
    """模拟 AuthRepository（dict-based 接口）。"""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.audit_logs: list[dict[str, Any]] = []

    def find_active_grant(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        now = datetime.now(UTC)
        for row in self.rows:
            if row["tenant_id"] != tenant_id or row["application_id"] != application_id:
                continue
            if row["status"] != "active":
                continue
            start = row.get("start_time")
            if start and start > now:
                continue
            expire = row.get("expire_time")
            if expire and expire <= now:
                continue
            return row
        return None

    def exists_active_grant(self, tenant_id: UUID, application_id: UUID) -> bool:
        return any(
            r["tenant_id"] == tenant_id
            and r["application_id"] == application_id
            and r["status"] == "active"
            for r in self.rows
        )

    def get_grant(self, instance_id: UUID) -> dict | None:
        return next((r for r in self.rows if r["id"] == instance_id), None)

    def create_grant(self, data: dict[str, Any]) -> UUID:
        instance_id = uuid4()
        data["id"] = instance_id
        self.rows.append(data)
        return instance_id

    def update_grant_status(self, instance_id: UUID, status: str) -> None:
        for row in self.rows:
            if row["id"] == instance_id:
                row["status"] = status
                break

    def update_apply_status(self, apply_id: UUID, status: str) -> None:
        pass  # 测试不关心申请单

    def append_audit_log(self, data: dict[str, Any]) -> None:
        self.audit_logs.append(data)


def test_auth_service_cache_hit():
    cache = InMemoryAuthCache()
    repo = FakeAuthRepo()
    svc = AuthService(repo, cache)

    tenant_id = uuid4()
    app_id = uuid4()

    # 第一次：DB 无记录 → has_auth=False，写负缓存
    r1 = asyncio.run(svc.check(tenant_id, app_id))
    assert r1.has_auth is False

    # 第二次：直接命中缓存（DB 仍无记录）
    r2 = asyncio.run(svc.check(tenant_id, app_id))
    assert r2.has_auth is False


def test_create_grant_active_then_auth_passes():
    cache = InMemoryAuthCache()
    repo = FakeAuthRepo()
    auth_svc = AuthService(repo, cache)
    grant_svc = GrantService(repo, auth_svc)

    tenant_id = uuid4()
    app_id = uuid4()
    now = datetime.now(UTC)

    req = CreateGrantRequest(
        tenant_id=tenant_id,
        app_id=app_id,
        auth_type=AuthType.FORMAL.value,
        contract_no="HT-2026-001",
        quota_json={"user_limit": 100},
        start_time=now - timedelta(minutes=1),
        expire_time=now + timedelta(days=365),
    )
    asyncio.run(grant_svc.create_grant(req))

    # 检查记录确实写入了
    assert len(repo.rows) == 1
    assert repo.rows[0]["status"] == "active"

    # 鉴权应通过
    result = asyncio.run(auth_svc.check(tenant_id, app_id))
    assert result.has_auth is True
    assert result.auth_info.auth_type == AuthType.FORMAL.value
    assert result.auth_info.quota["user_limit"] == 100

    # 审计日志写了一条 CREATE
    assert len(repo.audit_logs) == 1
    assert repo.audit_logs[0]["action"] == "CREATE"


def test_create_grant_rejects_duplicate_active():
    cache = InMemoryAuthCache()
    repo = FakeAuthRepo()
    auth_svc = AuthService(repo, cache)
    grant_svc = GrantService(repo, auth_svc)

    tenant_id = uuid4()
    app_id = uuid4()
    now = datetime.now(UTC)

    req = CreateGrantRequest(
        tenant_id=tenant_id,
        app_id=app_id,
        auth_type=AuthType.FORMAL.value,
        contract_no="HT-1",
        quota_json={},
        start_time=now - timedelta(minutes=1),
        expire_time=now + timedelta(days=30),
    )
    asyncio.run(grant_svc.create_grant(req))

    # 第二次同 tenant+app 应该拒绝
    try:
        asyncio.run(grant_svc.create_grant(req))
        assert False, "应该抛出 GrantError"
    except GrantError as exc:
        assert "ACTIVE" in str(exc)


def test_create_grant_with_past_expire_time_rejected():
    cache = InMemoryAuthCache()
    repo = FakeAuthRepo()
    auth_svc = AuthService(repo, cache)
    grant_svc = GrantService(repo, auth_svc)

    tenant_id = uuid4()
    app_id = uuid4()
    now = datetime.now(UTC)

    req = CreateGrantRequest(
        tenant_id=tenant_id,
        app_id=app_id,
        auth_type=AuthType.FORMAL.value,
        contract_no="HT-2",
        quota_json={},
        start_time=now - timedelta(minutes=1),
        expire_time=now - timedelta(days=1),
    )
    try:
        asyncio.run(grant_svc.create_grant(req))
        assert False, "应该拒绝"
    except GrantError as exc:
        assert "expire_time" in str(exc)


def test_recycle_grant_invalidates_cache():
    cache = InMemoryAuthCache()
    repo = FakeAuthRepo()
    auth_svc = AuthService(repo, cache)
    grant_svc = GrantService(repo, auth_svc)

    tenant_id = uuid4()
    app_id = uuid4()
    now = datetime.now(UTC)

    req = CreateGrantRequest(
        tenant_id=tenant_id,
        app_id=app_id,
        auth_type=AuthType.TRIAL.value,
        contract_no="",
        quota_json={},
        start_time=now - timedelta(minutes=1),
        expire_time=now + timedelta(days=7),
    )
    instance_id = asyncio.run(grant_svc.create_grant(req))

    # 先跑一次鉴权，把缓存填上
    asyncio.run(auth_svc.check(tenant_id, app_id))
    assert cache.store  # 缓存非空

    # 回收
    asyncio.run(grant_svc.recycle_grant(instance_id, operator_id=None, operator_name="ops"))

    # 缓存已失效
    key = f"auth:{tenant_id}:{app_id}"
    assert key not in cache.store

    # 鉴权返回 false
    result = asyncio.run(auth_svc.check(tenant_id, app_id))
    assert result.has_auth is False
