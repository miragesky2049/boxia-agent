"""部门的 PostgreSQL 仓储实现：物化路径树维护。"""

from typing import Any
from uuid import UUID

from sqlalchemy import Text, case, func, literal, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.entity.department import Department
from internal.infrastructure.model.department import DepartmentModel
from internal.infrastructure.model.employment import EmploymentModel


class PostgresDepartmentRepository:
    """基于 SQLAlchemy 的部门仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, department_id: UUID) -> Department | None:
        """按主键查询部门（租户归属由应用层校验）。"""
        row = self._session.get(DepartmentModel, department_id)
        return self._to_entity(row) if row else None

    def get_for_update(
        self, department_id: UUID, tenant_id: UUID | None = None
    ) -> Department | None:
        """按主键加行锁查询部门；传入租户时同时限定租户。"""
        stmt = select(DepartmentModel).where(DepartmentModel.id == department_id)
        if tenant_id is not None:
            stmt = stmt.where(DepartmentModel.tenant_id == tenant_id)
        row = self._session.scalar(stmt.with_for_update())
        return self._to_entity(row) if row else None

    def list_all(self, tenant_id: UUID) -> list[Department]:
        """按物化路径顺序返回租户全部部门。"""
        rows = self._session.scalars(
            select(DepartmentModel)
            .where(DepartmentModel.tenant_id == tenant_id)
            .order_by(DepartmentModel.path.asc())
        ).all()
        return [self._to_entity(row) for row in rows]

    def create(self, values: dict[str, Any]) -> Department:
        """创建部门。"""
        row = DepartmentModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, department_id: UUID, values: dict[str, Any]) -> Department | None:
        """更新部门基础字段（不含移动子树，移动走 reparent_subtree）。"""
        row = self._session.get(DepartmentModel, department_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, department_id: UUID) -> bool:
        """物理删除部门。"""
        row = self._session.get(DepartmentModel, department_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def code_exists(
        self, tenant_id: UUID, code: str, exclude_id: UUID | None = None
    ) -> bool:
        """租户内部门编码是否已存在（忽略大小写）。"""
        stmt = select(DepartmentModel.id).where(
            DepartmentModel.tenant_id == tenant_id,
            func.lower(DepartmentModel.code) == code.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(DepartmentModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def name_exists_under_parent(
        self,
        tenant_id: UUID,
        parent_id: UUID | None,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一父部门下名称是否已存在（根部门 parent_id 为空）。"""
        stmt = select(DepartmentModel.id).where(
            DepartmentModel.tenant_id == tenant_id,
            DepartmentModel.parent_id.is_not_distinct_from(parent_id),
            func.lower(DepartmentModel.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(DepartmentModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def exists_child(self, tenant_id: UUID, department_id: UUID) -> bool:
        """是否存在直接子部门。"""
        stmt = select(DepartmentModel.id).where(
            DepartmentModel.tenant_id == tenant_id,
            DepartmentModel.parent_id == department_id,
        )
        return self._session.scalar(stmt.limit(1)) is not None

    def count_employments(self, tenant_id: UUID, department_id: UUID) -> int:
        """统计部门下全部任职记录数（含历史记录）。"""
        total = self._session.scalar(
            select(func.count())
            .select_from(EmploymentModel)
            .where(
                EmploymentModel.tenant_id == tenant_id,
                EmploymentModel.department_id == department_id,
            )
        )
        return int(total or 0)

    def lock_subtree_and_parent(
        self,
        tenant_id: UUID,
        subtree_prefix: str,
        new_parent_id: UUID | None,
    ) -> list[Department]:
        """按 path 顺序锁定待移动子树与目标父行，统一加锁顺序防死锁。"""
        scope: ColumnElement[bool] = DepartmentModel.path.like(subtree_prefix + "%")
        if new_parent_id is not None:
            scope = or_(scope, DepartmentModel.id == new_parent_id)
        rows = self._session.scalars(
            select(DepartmentModel)
            .where(DepartmentModel.tenant_id == tenant_id, scope)
            .order_by(DepartmentModel.path.asc())
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
        old_lit = literal(old_prefix, Text)
        path_expr = literal(new_prefix, Text).concat(
            func.substr(DepartmentModel.path, func.char_length(old_lit) + 1)
        )
        stmt = (
            update(DepartmentModel)
            .where(
                DepartmentModel.tenant_id == tenant_id,
                DepartmentModel.path.like(old_prefix + "%"),
            )
            .values(
                parent_id=case(
                    (DepartmentModel.id == moved_id, new_parent_id),
                    else_=DepartmentModel.parent_id,
                ),
                path=path_expr,
                level=DepartmentModel.level + level_delta,
            )
        )
        self._session.execute(stmt)
        self._session.flush()

    @staticmethod
    def _to_entity(row: DepartmentModel) -> Department:
        return Department(
            id=row.id,
            tenant_id=row.tenant_id,
            parent_id=row.parent_id,
            name=row.name,
            code=row.code,
            path=row.path,
            level=row.level,
            sort_order=row.sort_order,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
