"""用户任职记录的 PostgreSQL 仓储实现。"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from internal.domain.entity.employment import Employment
from internal.infrastructure.model.access import UserModel
from internal.infrastructure.model.department import DepartmentModel
from internal.infrastructure.model.employment import EmploymentModel
from internal.infrastructure.model.hr_dictionary import HrDictionaryModel


class PostgresEmploymentRepository:
    """基于 SQLAlchemy 的任职记录仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, employment_id: UUID) -> Employment | None:
        """按主键查询任职（含用户、部门、汇报上级与字典展示字段）。"""
        row = self._session.execute(
            self._base_select().where(EmploymentModel.id == employment_id)
        ).first()
        return self._to_entity(row) if row else None

    def list_page(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        department_path_prefix: str | None,
        user_id: UUID | None,
        is_current: bool | None,
    ) -> tuple[list[Employment], int]:
        """分页查询任职记录，部门前缀命中本部门及下级。"""
        stmt = self._base_select().where(EmploymentModel.tenant_id == tenant_id)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    UserModel.username.ilike(pattern),
                    UserModel.display_name.ilike(pattern),
                    EmploymentModel.position.ilike(pattern),
                )
            )
        if department_path_prefix:
            stmt = stmt.where(DepartmentModel.path.like(department_path_prefix + "%"))
        if user_id is not None:
            stmt = stmt.where(EmploymentModel.user_id == user_id)
        if is_current is not None:
            stmt = stmt.where(EmploymentModel.is_current.is_(is_current))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.execute(
            stmt.order_by(
                EmploymentModel.started_at.desc(),
                EmploymentModel.created_at.desc(),
                EmploymentModel.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    def create(self, values: dict[str, Any]) -> Employment:
        """创建任职记录后回读展示字段。"""
        row = EmploymentModel(**values)
        self._session.add(row)
        self._session.flush()
        return self.get(row.id)  # type: ignore[return-value]

    def update(self, employment_id: UUID, values: dict[str, Any]) -> Employment | None:
        """更新任职记录字段后回读展示字段。"""
        row = self._session.get(EmploymentModel, employment_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        return self.get(employment_id)

    def delete(self, employment_id: UUID) -> bool:
        """物理删除任职记录。"""
        row = self._session.get(EmploymentModel, employment_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def get_current_for_update(self, tenant_id: UUID, user_id: UUID) -> Employment | None:
        """加行锁查询用户当前主任职。"""
        row = self._session.scalar(
            select(EmploymentModel)
            .where(
                EmploymentModel.tenant_id == tenant_id,
                EmploymentModel.user_id == user_id,
                EmploymentModel.is_current.is_(True),
            )
            .with_for_update()
        )
        return self._to_plain_entity(row) if row else None

    def map_current_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, tuple[UUID, str]]:
        """批量返回用户当前任职的 (部门id, 部门名)。"""
        if not user_ids:
            return {}
        rows = self._session.execute(
            select(
                EmploymentModel.user_id,
                EmploymentModel.department_id,
                DepartmentModel.name,
            )
            .join(
                DepartmentModel,
                and_(
                    DepartmentModel.id == EmploymentModel.department_id,
                    DepartmentModel.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .where(
                EmploymentModel.tenant_id == tenant_id,
                EmploymentModel.is_current.is_(True),
                EmploymentModel.user_id.in_(user_ids),
            )
            .distinct(EmploymentModel.user_id)
            .order_by(EmploymentModel.user_id, EmploymentModel.started_at.desc())
        ).all()
        return {user_id: (department_id, name) for user_id, department_id, name in rows}

    def list_current_user_ids_in_subtree(
        self, tenant_id: UUID, department_path_prefix: str
    ) -> set[UUID]:
        """返回当前任职部门落在给定部门前缀（本部门及下级）内的用户 ID。"""
        rows = self._session.scalars(
            select(EmploymentModel.user_id)
            .join(
                DepartmentModel,
                and_(
                    DepartmentModel.id == EmploymentModel.department_id,
                    DepartmentModel.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .where(
                EmploymentModel.tenant_id == tenant_id,
                EmploymentModel.is_current.is_(True),
                DepartmentModel.path.like(department_path_prefix + "%"),
            )
            .distinct()
        ).all()
        return set(rows)

    def get_current_department_brief(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[UUID, str] | None:
        """返回用户当前任职的 (部门id, 部门 path)；无当前任职返回 None。"""
        row = self._session.execute(
            select(EmploymentModel.department_id, DepartmentModel.path)
            .join(
                DepartmentModel,
                and_(
                    DepartmentModel.id == EmploymentModel.department_id,
                    DepartmentModel.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .where(
                EmploymentModel.tenant_id == tenant_id,
                EmploymentModel.user_id == user_id,
                EmploymentModel.is_current.is_(True),
            )
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    @staticmethod
    def _base_select():
        """任职表关联用户、部门、汇报上级用户与 HR 字典的查询构造器。"""
        manager_user = aliased(UserModel)
        employment_type_dict = aliased(HrDictionaryModel)
        job_level_dict = aliased(HrDictionaryModel)
        job_family_dict = aliased(HrDictionaryModel)
        return (
            select(
                EmploymentModel,
                UserModel.username.label("user_name"),
                UserModel.display_name.label("user_display_name"),
                DepartmentModel.name.label("department_name"),
                DepartmentModel.path.label("department_path"),
                manager_user.display_name.label("manager_name"),
                employment_type_dict.name.label("employment_type_name"),
                job_level_dict.name.label("job_level_name"),
                job_family_dict.name.label("job_family_name"),
            )
            .join(
                UserModel,
                and_(
                    UserModel.id == EmploymentModel.user_id,
                    UserModel.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .join(
                DepartmentModel,
                and_(
                    DepartmentModel.id == EmploymentModel.department_id,
                    DepartmentModel.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .outerjoin(
                manager_user,
                and_(
                    manager_user.id == EmploymentModel.manager_id,
                    manager_user.tenant_id == EmploymentModel.tenant_id,
                ),
            )
            .outerjoin(
                employment_type_dict,
                and_(
                    employment_type_dict.id == EmploymentModel.employment_type_id,
                    employment_type_dict.tenant_id == EmploymentModel.tenant_id,
                    employment_type_dict.category == "employment_type",
                ),
            )
            .outerjoin(
                job_level_dict,
                and_(
                    job_level_dict.id == EmploymentModel.job_level_id,
                    job_level_dict.tenant_id == EmploymentModel.tenant_id,
                    job_level_dict.category == "job_level",
                ),
            )
            .outerjoin(
                job_family_dict,
                and_(
                    job_family_dict.id == EmploymentModel.job_family_id,
                    job_family_dict.tenant_id == EmploymentModel.tenant_id,
                    job_family_dict.category == "job_family",
                ),
            )
        )

    @staticmethod
    def _to_entity(row: Any) -> Employment:
        model: EmploymentModel = row[0]
        return Employment(
            id=model.id,
            tenant_id=model.tenant_id,
            user_id=model.user_id,
            department_id=model.department_id,
            position=model.position,
            is_current=model.is_current,
            started_at=model.started_at,
            ended_at=model.ended_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
            employment_type_id=model.employment_type_id,
            job_level_id=model.job_level_id,
            job_family_id=model.job_family_id,
            manager_id=model.manager_id,
            work_location=model.work_location,
            cost_center=model.cost_center,
            contract_no=model.contract_no,
            weekly_hours=float(model.weekly_hours) if model.weekly_hours is not None else None,
            employment_nature=model.employment_nature,
            probation_started_at=model.probation_started_at,
            probation_ended_at=model.probation_ended_at,
            regularized_at=model.regularized_at,
            change_type=model.change_type,
            change_reason=model.change_reason,
            termination_type=model.termination_type,
            remark=model.remark,
            user_name=row.user_name,
            user_display_name=row.user_display_name,
            department_name=row.department_name,
            department_path=row.department_path,
            manager_name=row.manager_name,
            employment_type_name=row.employment_type_name,
            job_level_name=row.job_level_name,
            job_family_name=row.job_family_name,
        )

    @staticmethod
    def _to_plain_entity(row: EmploymentModel) -> Employment:
        return Employment(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            department_id=row.department_id,
            position=row.position,
            is_current=row.is_current,
            started_at=row.started_at,
            ended_at=row.ended_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            employment_type_id=row.employment_type_id,
            job_level_id=row.job_level_id,
            job_family_id=row.job_family_id,
            manager_id=row.manager_id,
            work_location=row.work_location,
            cost_center=row.cost_center,
            contract_no=row.contract_no,
            weekly_hours=float(row.weekly_hours) if row.weekly_hours is not None else None,
            employment_nature=row.employment_nature,
            probation_started_at=row.probation_started_at,
            probation_ended_at=row.probation_ended_at,
            regularized_at=row.regularized_at,
            change_type=row.change_type,
            change_reason=row.change_reason,
            termination_type=row.termination_type,
            remark=row.remark,
        )
