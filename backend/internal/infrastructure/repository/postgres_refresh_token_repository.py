"""刷新令牌的 PostgreSQL 仓储实现。"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from internal.domain.entity.refresh_token import RefreshToken
from internal.infrastructure.model.refresh_token import RefreshTokenModel


class PostgresRefreshTokenRepository:
    """基于 SQLAlchemy 的刷新令牌仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, values: dict[str, Any]) -> RefreshToken:
        """写入刷新令牌（仅哈希）。"""
        row = RefreshTokenModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """按哈希加行锁查询。"""
        row = self._session.scalar(
            select(RefreshTokenModel)
            .where(RefreshTokenModel.token_hash == token_hash)
            .with_for_update()
        )
        return self._to_entity(row) if row else None

    def rotate(self, old_id: int, replaced_by_id: int) -> None:
        """标记旧令牌已轮换并撤销。"""
        now = datetime.now(UTC)
        row = self._session.get(RefreshTokenModel, old_id)
        if row is None:
            return
        row.rotated_at = now
        row.revoked_at = now
        row.replaced_by_id = replaced_by_id
        self._session.flush()

    def revoke_family(self, family_id: UUID) -> int:
        """撤销同一会话族全部令牌。"""
        result = self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.family_id == family_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    def revoke_all_for_user(self, user_id: int) -> int:
        """撤销用户全部未撤销令牌。"""
        result = self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    def is_family_active(self, family_id: UUID) -> bool:
        """会话族是否仍有有效令牌。"""
        stmt = select(RefreshTokenModel.id).where(
            RefreshTokenModel.family_id == family_id,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > datetime.now(UTC),
        )
        return self._session.scalar(stmt) is not None

    def delete_expired(self, before: datetime) -> int:
        """清理过期令牌。"""
        result = self._session.execute(
            delete(RefreshTokenModel).where(RefreshTokenModel.expires_at < before)
        )
        self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _to_entity(row: RefreshTokenModel) -> RefreshToken:
        return RefreshToken(
            id=row.id,
            user_id=row.user_id,
            token_hash=row.token_hash,
            family_id=row.family_id,
            token_version=row.token_version,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            rotated_at=row.rotated_at,
            revoked_at=row.revoked_at,
            replaced_by_id=row.replaced_by_id,
            ip=row.ip,
            user_agent=row.user_agent,
        )
