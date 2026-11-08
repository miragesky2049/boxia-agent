"""AuthService：业务应用统一鉴权入口。

入参：tenant_id, app_id
返回：has_auth + auth_info（auth_type / quota / expire_time）

流程：
1. 先读 Redis 缓存 key=`auth:{tenant_id}:{app_id}`
2. 未命中查 DB（tenant_app_auth status=ACTIVE 且在有效期内）
3. 命中结果写缓存 TTL=3 分钟
4. 未命中也写缓存（负缓存，TTL 短）防止穿透
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from internal.domain.auth.cache import AuthCache
from internal.domain.entity.auth_constants import AUTH_CACHE_KEY_PREFIX, AUTH_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthInfo:
    auth_type: str
    quota: dict[str, Any]
    expire_time: str | None


@dataclass(frozen=True)
class AuthResult:
    has_auth: bool
    auth_info: AuthInfo | None


class AuthService:
    def __init__(self, auth_repo: Any, cache: AuthCache | None = None) -> None:
        self._repo = auth_repo
        self._cache = cache

    async def check(self, tenant_id: UUID, app_id: UUID) -> AuthResult:
        key = self._cache_key(tenant_id, app_id)

        if self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                return self._from_cache(cached)

        row = self._repo.find_active_grant(tenant_id, app_id)
        result = self._from_row(row)

        if self._cache is not None:
            await self._cache.set(key, self._to_cache(result), ttl_seconds=AUTH_CACHE_TTL_SECONDS)

        return result

    async def invalidate(self, tenant_id: UUID, app_id: UUID) -> None:
        """授权变更后调用：主动失效缓存。"""
        if self._cache is None:
            return
        key = self._cache_key(tenant_id, app_id)
        await self._cache.delete(key)
        logger.info("鉴权缓存已失效: %s", key)

    @staticmethod
    def _cache_key(tenant_id: UUID, app_id: UUID) -> str:
        return f"{AUTH_CACHE_KEY_PREFIX}:{tenant_id}:{app_id}"

    @staticmethod
    def _from_row(row: dict | None) -> AuthResult:
        if row is None:
            return AuthResult(has_auth=False, auth_info=None)
        expire_time = row.get("expire_time")
        if expire_time is not None and hasattr(expire_time, "isoformat"):
            expire_str = expire_time.isoformat()
        else:
            expire_str = str(expire_time) if expire_time else None
        return AuthResult(
            has_auth=True,
            auth_info=AuthInfo(
                auth_type=row.get("auth_type", ""),
                quota=dict(row.get("quota_json") or {}),
                expire_time=expire_str,
            ),
        )

    @staticmethod
    def _to_cache(result: AuthResult) -> dict[str, Any]:
        if not result.has_auth or result.auth_info is None:
            return {"has_auth": False}
        return {
            "has_auth": True,
            "auth_info": {
                "auth_type": result.auth_info.auth_type,
                "quota": result.auth_info.quota,
                "expire_time": result.auth_info.expire_time,
            },
        }

    @staticmethod
    def _from_cache(cached: dict[str, Any]) -> AuthResult:
        if not cached.get("has_auth"):
            return AuthResult(has_auth=False, auth_info=None)
        info = cached.get("auth_info") or {}
        return AuthResult(
            has_auth=True,
            auth_info=AuthInfo(
                auth_type=info.get("auth_type", ""),
                quota=info.get("quota") or {},
                expire_time=info.get("expire_time"),
            ),
        )
