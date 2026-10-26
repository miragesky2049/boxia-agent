"""用户任职记录 ORM 模型。"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
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
        CheckConstraint(
            "(is_current AND ended_at IS NULL) "
            "OR (NOT is_current AND ended_at IS NOT NULL)",
            name="ck_emp_current_ended",
        ),
        CheckConstraint(
            "ended_at IS NULL OR started_at <= ended_at",
            name="ck_emp_date_range",
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
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    department_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    position: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    started_at: Mapped[date] = mapped_column(Date, nullable=False)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
