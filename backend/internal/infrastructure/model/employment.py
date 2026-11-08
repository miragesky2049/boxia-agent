"""用户任职记录 ORM 模型。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class EmploymentModel(Base):
    """user_employments 表。"""

    __tablename__ = "user_employments"
    __table_args__ = (
        # 迁移建表时带单列租户外键，模型补齐保持与库一致（alembic check 不再报 remove_fk）
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_user_employments_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_user_employments_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_user_employments_department",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "manager_id"],
            ["users.tenant_id", "users.id"],
            name="fk_user_employments_manager",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(is_current AND ended_at IS NULL) OR (NOT is_current AND ended_at IS NOT NULL)",
            name="ck_emp_current_ended",
        ),
        CheckConstraint(
            "ended_at IS NULL OR started_at <= ended_at",
            name="ck_emp_date_range",
        ),
        CheckConstraint(
            "employment_nature IS NULL OR employment_nature IN "
            "('regular', 'dispatch', 'outsourced', 'intern')",
            name="ck_emp_nature",
        ),
        CheckConstraint(
            "change_type IS NULL OR change_type IN "
            "('hire', 'transfer', 'promotion', 'demotion', 'reorganization')",
            name="ck_emp_change_type",
        ),
        CheckConstraint(
            "termination_type IS NULL OR termination_type IN "
            "('resignation', 'dismissal', 'layoff', 'retirement')",
            name="ck_emp_termination_type",
        ),
        CheckConstraint(
            "probation_started_at IS NULL OR probation_ended_at IS NULL "
            "OR probation_started_at <= probation_ended_at",
            name="ck_emp_probation_range",
        ),
        Index(
            "ux_emp_current_user",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_emp_tenant_dept_current", "tenant_id", "department_id", "is_current"),
        Index("ix_emp_tenant_user", "tenant_id", "user_id"),
        Index("ix_emp_manager", "tenant_id", "manager_id"),
        Index("ix_emp_employment_type", "tenant_id", "employment_type_id"),
        Index("ix_emp_job_level", "tenant_id", "job_level_id"),
        Index("ix_emp_job_family", "tenant_id", "job_family_id"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    department_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    position: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    started_at: Mapped[date] = mapped_column(Date, nullable=False)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # HR 字典外键（应用层校验同租户与类别匹配）
    employment_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    job_level_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    job_family_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    manager_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # 用工基础信息
    work_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weekly_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    employment_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 试用期与转正
    probation_started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    probation_ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    regularized_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 变动与离职
    change_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    termination_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
