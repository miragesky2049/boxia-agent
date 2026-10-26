"""资源授权的 PostgreSQL 仓储实现。"""

from typing import cast
from uuid import UUID

from sqlalchemy import and_, delete, distinct, func, insert, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.entity.access import GrantSummary, ResourceGrant
from internal.infrastructure.model.access import ResourceGrantModel


class PostgresResourceGrantRepository:
    """基于 SQLAlchemy 的资源授权仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def list_for_resource(
        self, resource_type: str, resource_id: UUID, tenant_id: UUID | None = None
    ) -> list[ResourceGrant]:
        """读取资源授权；指定租户时只返回该租户的授权。"""
        stmt = select(ResourceGrantModel).where(
            ResourceGrantModel.resource_type == resource_type,
            ResourceGrantModel.resource_id == resource_id,
        )
        if tenant_id is not None:
            stmt = stmt.where(ResourceGrantModel.tenant_id == tenant_id)
        rows = self._session.scalars(
            stmt.order_by(
                ResourceGrantModel.tenant_id.asc(),
                ResourceGrantModel.role_id.asc().nullsfirst(),
            )
        ).all()
        return [self._to_entity(row) for row in rows]

    def list_for_resources(
        self,
        resource_type: str,
        resource_ids: list[UUID],
        tenant_id: UUID | None = None,
    ) -> list[ResourceGrant]:
        """批量读取多个资源的授权；指定租户时只返回该租户的授权。"""
        if not resource_ids:
            return []
        stmt = select(ResourceGrantModel).where(
            ResourceGrantModel.resource_type == resource_type,
            ResourceGrantModel.resource_id.in_(resource_ids),
        )
        if tenant_id is not None:
            stmt = stmt.where(ResourceGrantModel.tenant_id == tenant_id)
        rows = self._session.scalars(stmt).all()
        return [self._to_entity(row) for row in rows]

    def summary_for_resources(
        self,
        resource_type: str,
        resource_ids: list[UUID],
        tenant_id: UUID | None = None,
    ) -> dict[UUID, GrantSummary]:
        """按资源聚合授权数量，避免列表加载全量授权明细。"""
        if not resource_ids:
            return {}
        stmt = (
            select(
                ResourceGrantModel.resource_id,
                func.count().label("grant_count"),
                func.count(distinct(ResourceGrantModel.tenant_id)).label("tenant_count"),
                func.count(distinct(ResourceGrantModel.role_id)).label("role_count"),
            )
            .where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id.in_(resource_ids),
            )
            .group_by(ResourceGrantModel.resource_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(ResourceGrantModel.tenant_id == tenant_id)
        rows = self._session.execute(stmt).all()
        return {
            row.resource_id: GrantSummary(
                resource_id=row.resource_id,
                grant_count=int(row.grant_count),
                tenant_count=int(row.tenant_count),
                role_count=int(row.role_count),
            )
            for row in rows
        }

    def lock_resources(self, resource_type: str, resource_ids: list[UUID]) -> None:
        """按排序后的资源顺序获取事务级仲裁锁，避免批量写入死锁。"""
        for resource_id in sorted(set(resource_ids)):
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"{resource_type}:{resource_id}"},
            )

    def replace_for_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        grants: list[tuple[UUID, UUID | None]],
        granted_by: UUID | None,
    ) -> None:
        """整体替换资源授权；使用事务级 advisory lock 串行化同一资源的并发写入。"""
        lock_key = f"{resource_type}:{resource_id}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key}
        )
        # 平台资源同时存在“按租户授权”和“按平台角色授权”，这里只替换租户维度
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id == resource_id,
                ResourceGrantModel.tenant_id.is_not(None),
            )
        )
        if grants:
            self._session.execute(
                insert(ResourceGrantModel),
                [
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "granted_by": granted_by,
                    }
                    for tenant_id, role_id in grants
                ],
            )
        self._session.flush()

    def replace_for_tenant(
        self,
        resource_type: str,
        resource_id: UUID,
        tenant_id: UUID,
        role_ids: list[UUID] | None,
        granted_by: UUID | None,
    ) -> None:
        """整体替换某租户对资源的授权；role_ids 为 None 表示整个租户。"""
        lock_key = f"{resource_type}:{resource_id}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key}
        )
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id == resource_id,
                ResourceGrantModel.tenant_id == tenant_id,
            )
        )
        if role_ids is None:
            self._session.execute(
                insert(ResourceGrantModel).values(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    tenant_id=tenant_id,
                    role_id=None,
                    granted_by=granted_by,
                )
            )
        else:
            unique_role_ids = sorted(set(role_ids))
            if unique_role_ids:
                self._session.execute(
                    insert(ResourceGrantModel),
                    [
                        {
                            "resource_type": resource_type,
                            "resource_id": resource_id,
                            "tenant_id": tenant_id,
                            "role_id": role_id,
                            "granted_by": granted_by,
                        }
                        for role_id in unique_role_ids
                    ],
                )
        self._session.flush()

    def delete_for_resources(self, resource_type: str, resource_ids: list[UUID]) -> None:
        """批量删除多个资源的全部授权。"""
        if not resource_ids:
            return
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id.in_(resource_ids),
            )
        )
        self._session.flush()

    def delete_for_tenant_resources(
        self, resource_type: str, resource_ids: list[UUID], tenant_id: UUID
    ) -> None:
        """批量删除某租户对多个资源的授权，不影响其他租户。"""
        if not resource_ids:
            return
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id.in_(resource_ids),
                ResourceGrantModel.tenant_id == tenant_id,
            )
        )
        self._session.flush()

    def delete_for_resource(self, resource_type: str, resource_id: UUID) -> None:
        """删除资源全部授权。"""
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id == resource_id,
            )
        )
        self._session.flush()

    def count_for_role(self, role_id: UUID) -> int:
        """统计角色被授权次数。"""
        count = self._session.scalar(
            select(func.count())
            .select_from(ResourceGrantModel)
            .where(ResourceGrantModel.role_id == role_id)
        )
        return int(count or 0)

    def list_granted_resource_ids(self, role_id: UUID, resource_type: str) -> set[UUID]:
        """读取角色在某类资源上已获授权的资源 ID。"""
        rows = self._session.scalars(
            select(ResourceGrantModel.resource_id).where(
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
            )
        ).all()
        return set(rows)

    def list_effective_granted_resource_ids(
        self, role_id: UUID, tenant_id: UUID, resource_type: str
    ) -> set[UUID]:
        """读取角色有效授权的资源 ID：本角色显式授权或整租户授权。"""
        rows = self._session.scalars(
            select(ResourceGrantModel.resource_id).where(
                ResourceGrantModel.tenant_id == tenant_id,
                ResourceGrantModel.resource_type == resource_type,
                or_(
                    ResourceGrantModel.role_id == role_id,
                    ResourceGrantModel.role_id.is_(None),
                ),
            )
        ).all()
        return set(rows)

    def count_effective_granted(self, role_id: UUID, tenant_id: UUID, resource_type: str) -> int:
        """统计角色在某类资源上的有效授权数量。"""
        count = self._session.scalar(
            select(func.count(distinct(ResourceGrantModel.resource_id))).where(
                ResourceGrantModel.tenant_id == tenant_id,
                ResourceGrantModel.resource_type == resource_type,
                or_(
                    ResourceGrantModel.role_id == role_id,
                    ResourceGrantModel.role_id.is_(None),
                ),
            )
        )
        return int(count or 0)

    def list_tenant_wide_resource_ids(self, tenant_id: UUID, resource_type: str) -> set[UUID]:
        """读取某租户整租户授权的资源 ID。"""
        rows = self._session.scalars(
            select(ResourceGrantModel.resource_id).where(
                ResourceGrantModel.tenant_id == tenant_id,
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.role_id.is_(None),
            )
        ).all()
        return set(rows)

    def has_tenant_wide(self, resource_type: str, resource_id: UUID, tenant_id: UUID) -> bool:
        """资源是否存在对指定租户的整租户授权。"""
        row = self._session.scalar(
            select(ResourceGrantModel.id)
            .where(
                ResourceGrantModel.tenant_id == tenant_id,
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.resource_id == resource_id,
                ResourceGrantModel.role_id.is_(None),
            )
            .limit(1)
        )
        return row is not None

    def list_for_role(self, role_id: UUID, resource_type: str) -> list[ResourceGrant]:
        """读取角色在某类资源上的全部授权明细。"""
        rows = self._session.scalars(
            select(ResourceGrantModel)
            .where(
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
            )
            .order_by(ResourceGrantModel.resource_id.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def replace_for_role(
        self,
        role_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换角色在某类资源上的授权。"""
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
                ResourceGrantModel.tenant_id == tenant_id,
            )
        )
        unique_ids = sorted(set(resource_ids))
        if unique_ids:
            self._session.execute(
                insert(ResourceGrantModel),
                [
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "granted_by": granted_by,
                    }
                    for resource_id in unique_ids
                ],
            )
        self._session.flush()

    def add_for_role(
        self,
        role_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """追加角色授权，重复授权自动跳过。"""
        unique_ids = sorted(set(resource_ids))
        if not unique_ids:
            return 0
        stmt = (
            pg_insert(ResourceGrantModel)
            .values(
                [
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "granted_by": granted_by,
                    }
                    for resource_id in unique_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["resource_type", "resource_id", "tenant_id", "role_id"],
                index_where=ResourceGrantModel.role_id.is_not(None),
            )
            .returning(ResourceGrantModel.id)
        )
        # Rowcount 在批量 INSERT ... ON CONFLICT 下不可靠，改用 RETURNING 统计实际写入
        inserted = self._session.execute(stmt).scalars().all()
        self._session.flush()
        return len(inserted)

    def remove_for_role(self, role_id: UUID, resource_type: str, resource_id: UUID) -> bool:
        """删除角色对单个资源的授权。"""
        result = cast(
            CursorResult,
            self._session.execute(
                delete(ResourceGrantModel).where(
                    ResourceGrantModel.role_id == role_id,
                    ResourceGrantModel.resource_type == resource_type,
                    ResourceGrantModel.resource_id == resource_id,
                )
            ),
        )
        self._session.flush()
        return bool(result.rowcount)

    def list_platform_granted_resource_ids(self, role_id: UUID, resource_type: str) -> set[UUID]:
        """读取平台角色在某类平台资源上已获授权的资源 ID。"""
        rows = self._session.scalars(
            select(ResourceGrantModel.resource_id).where(
                ResourceGrantModel.tenant_id.is_(None),
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
            )
        ).all()
        return set(rows)

    def count_platform_granted(self, role_id: UUID, resource_type: str) -> int:
        """统计平台角色在某类平台资源上的有效授权数量。"""
        count = self._session.scalar(
            select(func.count(distinct(ResourceGrantModel.resource_id))).where(
                ResourceGrantModel.tenant_id.is_(None),
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
            )
        )
        return int(count or 0)

    def replace_for_platform_role(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换平台角色在某类平台资源上的授权。"""
        self._session.execute(
            delete(ResourceGrantModel).where(
                ResourceGrantModel.tenant_id.is_(None),
                ResourceGrantModel.role_id == role_id,
                ResourceGrantModel.resource_type == resource_type,
            )
        )
        unique_ids = sorted(set(resource_ids))
        if unique_ids:
            self._session.execute(
                insert(ResourceGrantModel),
                [
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "tenant_id": None,
                        "role_id": role_id,
                        "granted_by": granted_by,
                    }
                    for resource_id in unique_ids
                ],
            )
        self._session.flush()

    def add_for_platform_role(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """追加平台角色授权，重复授权自动跳过。"""
        unique_ids = sorted(set(resource_ids))
        if not unique_ids:
            return 0
        stmt = (
            pg_insert(ResourceGrantModel)
            .values(
                [
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "tenant_id": None,
                        "role_id": role_id,
                        "granted_by": granted_by,
                    }
                    for resource_id in unique_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["resource_type", "resource_id", "role_id"],
                # 必须与 ux_resource_grants_platform_role 的部分索引谓词完全一致
                index_where=and_(
                    ResourceGrantModel.tenant_id.is_(None),
                    ResourceGrantModel.role_id.is_not(None),
                ),
            )
            .returning(ResourceGrantModel.id)
        )
        inserted = self._session.execute(stmt).scalars().all()
        self._session.flush()
        return len(inserted)

    def remove_for_platform_role(
        self, role_id: UUID, resource_type: str, resource_id: UUID
    ) -> bool:
        """删除平台角色对单个平台资源的授权。"""
        result = cast(
            CursorResult,
            self._session.execute(
                delete(ResourceGrantModel).where(
                    ResourceGrantModel.tenant_id.is_(None),
                    ResourceGrantModel.role_id == role_id,
                    ResourceGrantModel.resource_type == resource_type,
                    ResourceGrantModel.resource_id == resource_id,
                )
            ),
        )
        self._session.flush()
        return bool(result.rowcount)

    @staticmethod
    def _to_entity(row: ResourceGrantModel) -> ResourceGrant:
        return ResourceGrant(
            id=row.id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            tenant_id=row.tenant_id,
            role_id=row.role_id,
            granted_by=row.granted_by,
            created_at=row.created_at,
        )
