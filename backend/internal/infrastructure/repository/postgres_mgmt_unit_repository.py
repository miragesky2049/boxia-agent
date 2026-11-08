"""管理单元的 PostgreSQL 仓储实现：物化路径树维护 + 部门/人员关联。"""

from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, func, insert, literal, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.entity.mgmt_unit import (
    ManagementUnit,
    MgmtUnitDepartment,
    MgmtUnitUser,
)
from internal.infrastructure.model.mgmt_unit import (
    MgmtUnitDepartmentModel,
    MgmtUnitModel,
    MgmtUnitUserModel,
)
from internal.infrastructure.model.user_mgmt_unit_grant import UserMgmtUnitGrantModel


class PostgresMgmtUnitRepository:
    """基于 SQLAlchemy 的管理单元仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, unit_id: UUID) -> ManagementUnit | None:
        """按主键查询管理单元（租户归属由应用层校验）。"""
        row = self._session.get(MgmtUnitModel, unit_id)
        return self._to_entity(row) if row else None

    def get_for_update(self, unit_id: UUID, tenant_id: UUID | None = None) -> ManagementUnit | None:
        """按主键加行锁查询管理单元；传入租户时同时限定租户。"""
        stmt = select(MgmtUnitModel).where(MgmtUnitModel.id == unit_id)
        if tenant_id is not None:
            stmt = stmt.where(MgmtUnitModel.tenant_id == tenant_id)
        row = self._session.scalar(stmt.with_for_update())
        return self._to_entity(row) if row else None

    def list_all(self, tenant_id: UUID, include_inactive: bool = True) -> list[ManagementUnit]:
        """按物化路径顺序返回租户全部管理单元。"""
        stmt = select(MgmtUnitModel).where(MgmtUnitModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(MgmtUnitModel.is_active.is_(True))
        rows = self._session.scalars(stmt.order_by(MgmtUnitModel.path.asc())).all()
        return [self._to_entity(row) for row in rows]

    def list_active(self, tenant_id: UUID) -> list[ManagementUnit]:
        """仅返回启用中的管理单元，用于授权勾选弹窗。"""
        return self.list_all(tenant_id, include_inactive=False)

    def create(self, values: dict[str, Any]) -> ManagementUnit:
        """创建管理单元。"""
        row = MgmtUnitModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, unit_id: UUID, values: dict[str, Any]) -> ManagementUnit | None:
        """更新管理单元基础字段（不含移动子树，移动走 reparent_subtree）。"""
        row = self._session.get(MgmtUnitModel, unit_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, unit_id: UUID) -> bool:
        """物理删除管理单元。"""
        row = self._session.get(MgmtUnitModel, unit_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def code_exists(self, tenant_id: UUID, code: str, exclude_id: UUID | None = None) -> bool:
        """租户内管理单元编码是否已存在（忽略大小写）。"""
        stmt = select(MgmtUnitModel.id).where(
            MgmtUnitModel.tenant_id == tenant_id,
            func.lower(MgmtUnitModel.code) == code.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(MgmtUnitModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def name_exists_under_parent(
        self,
        tenant_id: UUID,
        parent_id: UUID | None,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一父单元下名称是否已存在（根单元父 id 为空）。"""
        stmt = select(MgmtUnitModel.id).where(
            MgmtUnitModel.tenant_id == tenant_id,
            MgmtUnitModel.parent_id.is_not_distinct_from(parent_id),
            func.lower(MgmtUnitModel.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(MgmtUnitModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def exists_child(self, tenant_id: UUID, unit_id: UUID) -> bool:
        """是否存在直接子单元。"""
        stmt = select(MgmtUnitModel.id).where(
            MgmtUnitModel.tenant_id == tenant_id,
            MgmtUnitModel.parent_id == unit_id,
        )
        return self._session.scalar(stmt.limit(1)) is not None

    def list_departments(self, unit_id: UUID) -> list[MgmtUnitDepartment]:
        """读取管理单元已关联的部门列表。"""
        rows = self._session.execute(
            select(
                MgmtUnitDepartmentModel.unit_id,
                MgmtUnitDepartmentModel.department_id,
                MgmtUnitDepartmentModel.include_subtree,
            ).where(MgmtUnitDepartmentModel.unit_id == unit_id)
        ).all()
        return [
            MgmtUnitDepartment(
                unit_id=row.unit_id,
                department_id=row.department_id,
                include_subtree=row.include_subtree,
            )
            for row in rows
        ]

    def list_users(self, unit_id: UUID) -> list[MgmtUnitUser]:
        """读取管理单元已关联的人员列表。"""
        rows = self._session.execute(
            select(MgmtUnitUserModel.unit_id, MgmtUnitUserModel.user_id).where(
                MgmtUnitUserModel.unit_id == unit_id
            )
        ).all()
        return [MgmtUnitUser(unit_id=row.unit_id, user_id=row.user_id) for row in rows]

    def replace_departments(self, unit_id: UUID, bindings: list[tuple[UUID, bool]]) -> None:
        """整体替换管理单元的部门关联。"""
        self._session.execute(
            delete(MgmtUnitDepartmentModel).where(MgmtUnitDepartmentModel.unit_id == unit_id)
        )
        if bindings:
            self._session.execute(
                insert(MgmtUnitDepartmentModel),
                [
                    {"unit_id": unit_id, "department_id": dept_id, "include_subtree": flag}
                    for dept_id, flag in bindings
                ],
            )
        self._session.flush()

    def replace_users(self, unit_id: UUID, user_ids: list[UUID]) -> None:
        """整体替换管理单元的人员关联。"""
        self._session.execute(delete(MgmtUnitUserModel).where(MgmtUnitUserModel.unit_id == unit_id))
        if user_ids:
            self._session.execute(
                insert(MgmtUnitUserModel),
                [{"unit_id": unit_id, "user_id": user_id} for user_id in user_ids],
            )
        self._session.flush()

    def list_departments_for_units(self, unit_ids: list[UUID]) -> list[MgmtUnitDepartment]:
        """批量读取多个单元的部门关联，避免 N+1。"""
        if not unit_ids:
            return []
        rows = self._session.execute(
            select(
                MgmtUnitDepartmentModel.unit_id,
                MgmtUnitDepartmentModel.department_id,
                MgmtUnitDepartmentModel.include_subtree,
            ).where(MgmtUnitDepartmentModel.unit_id.in_(unit_ids))
        ).all()
        return [
            MgmtUnitDepartment(
                unit_id=row.unit_id,
                department_id=row.department_id,
                include_subtree=row.include_subtree,
            )
            for row in rows
        ]

    def list_users_for_units(self, unit_ids: list[UUID]) -> list[MgmtUnitUser]:
        """批量读取多个单元的人员关联，避免 N+1。"""
        if not unit_ids:
            return []
        rows = self._session.execute(
            select(MgmtUnitUserModel.unit_id, MgmtUnitUserModel.user_id).where(
                MgmtUnitUserModel.unit_id.in_(unit_ids)
            )
        ).all()
        return [MgmtUnitUser(unit_id=row.unit_id, user_id=row.user_id) for row in rows]

    def count_user_grants(self, tenant_id: UUID, unit_id: UUID) -> int:
        """统计该单元被授权给了多少用户（删除前保护）。"""
        total = self._session.scalar(
            select(func.count())
            .select_from(UserMgmtUnitGrantModel)
            .where(
                UserMgmtUnitGrantModel.tenant_id == tenant_id,
                UserMgmtUnitGrantModel.unit_id == unit_id,
            )
        )
        return int(total or 0)

    def lock_subtree_and_parent(
        self,
        tenant_id: UUID,
        subtree_prefix: str,
        new_parent_id: UUID | None,
    ) -> list[ManagementUnit]:
        """按 path 顺序锁定待移动子树与目标父行，统一加锁顺序防死锁。"""
        scope: ColumnElement[bool] = MgmtUnitModel.path.like(subtree_prefix + "%")
        if new_parent_id is not None:
            scope = or_(scope, MgmtUnitModel.id == new_parent_id)
        rows = self._session.scalars(
            select(MgmtUnitModel)
            .where(MgmtUnitModel.tenant_id == tenant_id, scope)
            .order_by(MgmtUnitModel.path.asc())
            .with_for_update()
        ).all()
        return [self._to_entity(row) for row in rows]

    def reparent_subtree(
        self,
        tenant_id: UUID,
        moved_id: UUID,
        old_prefix: str,
        new_prefix: str,
        new_parent_id: UUID | None,
        level_delta: int,
    ) -> None:
        """整体平移子树：path 替换前缀、level 加偏移量，仅移动节点自身更新 parent_id。"""
        old_lit = literal(old_prefix)
        path_expr = literal(new_prefix).concat(
            func.substr(MgmtUnitModel.path, func.char_length(old_lit) + 1)
        )
        stmt = (
            update(MgmtUnitModel)
            .where(
                MgmtUnitModel.tenant_id == tenant_id,
                MgmtUnitModel.path.like(old_prefix + "%"),
            )
            .values(
                parent_id=case(
                    (MgmtUnitModel.id == moved_id, new_parent_id),
                    else_=MgmtUnitModel.parent_id,
                ),
                path=path_expr,
                level=MgmtUnitModel.level + level_delta,
            )
        )
        self._session.execute(stmt)
        self._session.flush()

    @staticmethod
    def _to_entity(row: MgmtUnitModel) -> ManagementUnit:
        return ManagementUnit(
            id=row.id,
            tenant_id=row.tenant_id,
            parent_id=row.parent_id,
            name=row.name,
            code=row.code,
            path=row.path,
            level=row.level,
            sort_order=row.sort_order,
            attrs=dict(row.attrs or {}),
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
