"""用户被授权管理单元的 PostgreSQL 仓储实现。"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.entity.user_mgmt_unit_grant import UserMgmtUnitGrant
from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.mgmt_unit import MgmtUnitModel
from internal.infrastructure.model.user_mgmt_unit_grant import UserMgmtUnitGrantModel


class PostgresUserMgmtUnitGrantRepository:
    """基于 SQLAlchemy 的用户管理单元授权仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def list_for_user(self, tenant_id: UUID, user_id: UUID) -> list[UserMgmtUnitGrant]:
        """读取某用户在本租户被授权的全部管理单元。"""
        rows = self._session.scalars(
            select(UserMgmtUnitGrantModel).where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.user_id == user_id,
            )
        ).all()
        return [self._to_entity(row) for row in rows]

    def list_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, list[UserMgmtUnitGrant]]:
        """批量读取多个用户的授权。"""
        if not user_ids:
            return {}
        rows = self._session.scalars(
            select(UserMgmtUnitGrantModel).where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.user_id.in_(user_ids),
            )
        ).all()
        result: dict[UUID, list[UserMgmtUnitGrant]] = {}
        for row in rows:
            result.setdefault(row.user_id, []).append(self._to_entity(row))
        return result

    def list_unit_ids_for_user(self, tenant_id: UUID, user_id: UUID) -> set[UUID]:
        """读取某用户被授权的单元 id 集合（行过滤用）。"""
        rows = self._session.scalars(
            select(UserMgmtUnitGrantModel.unit_id).where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.user_id == user_id,
            )
        ).all()
        return set(rows)

    def add_grants(
        self,
        tenant_id: UUID,
        user_ids: list[UUID],
        unit_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """批量追加（user, unit）授权；已存在的组合自动跳过，返回新增数量。"""
        if not user_ids or not unit_ids:
            return 0
        # 先查出已存在的组合
        existing = set(
            self._session.execute(
                select(UserMgmtUnitGrantModel.user_id, UserMgmtUnitGrantModel.unit_id).where(
                    UserMgmtUnitGrantModel.tenant_id == tenant_id,
                    UserMgmtUnitGrantModel.user_id.in_(user_ids),
                    UserMgmtUnitGrantModel.unit_id.in_(unit_ids),
                )
            ).all()
        )
        payload = []
        for user_id in user_ids:
            for unit_id in unit_ids:
                if (user_id, unit_id) in existing:
                    continue
                payload.append(
                    {
                        "id": new_uuid(),
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "unit_id": unit_id,
                        "granted_by": granted_by,
                    }
                )
        if payload:
            self._session.execute(insert(UserMgmtUnitGrantModel), payload)
            self._session.flush()
        return len(payload)

    def replace_for_users(
        self,
        tenant_id: UUID,
        user_ids: list[UUID],
        unit_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换每个目标用户的管理单元授权：先清空再写入；unit_ids 为空即清空。"""
        if not user_ids:
            return
        self._session.execute(
            delete(UserMgmtUnitGrantModel).where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.user_id.in_(user_ids),
            )
        )
        if unit_ids:
            payload = [
                {
                    "id": new_uuid(),
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "unit_id": unit_id,
                    "granted_by": granted_by,
                }
                for user_id in user_ids
                for unit_id in unit_ids
            ]
            self._session.execute(insert(UserMgmtUnitGrantModel), payload)
        self._session.flush()

    def remove_grant(self, tenant_id: UUID, user_id: UUID, unit_id: UUID) -> bool:
        """移除某用户对某单元的授权。"""
        result = self._session.execute(
            delete(UserMgmtUnitGrantModel).where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.user_id == user_id,
                UserMgmtUnitGrantModel.unit_id == unit_id,
            )
        )
        self._session.flush()
        return int(cast(CursorResult[Any], result).rowcount or 0) > 0

    def list_unit_names(self, tenant_id: UUID, unit_ids: list[UUID]) -> dict[UUID, str]:
        """批量读取单元 id -> 名称映射（前端展示用）。"""
        if not unit_ids:
            return {}
        rows = self._session.execute(
            select(MgmtUnitModel.id, MgmtUnitModel.name).where(
                MgmtUnitModel.tenant_id == tenant_id,
                MgmtUnitModel.id.in_(unit_ids),
            )
        ).all()
        return {row.id: row.name for row in rows}

    @staticmethod
    def _to_entity(row: UserMgmtUnitGrantModel) -> UserMgmtUnitGrant:
        return UserMgmtUnitGrant(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            unit_id=row.unit_id,
            granted_by=row.granted_by,
            created_at=row.created_at,
        )
