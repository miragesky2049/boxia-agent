"""HR 字典 ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class HrDictionaryModel(Base):
    """hr_dictionaries 表：按 category 区分雇佣类型/岗位职级/岗位序列。"""

    __tablename__ = "hr_dictionaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "category", "code", name="uq_hr_dictionaries_tenant_category_code"),
        CheckConstraint(
            "category IN ('employment_type', 'job_level', 'job_family')",
            name="ck_hr_dictionaries_category",
        ),
        CheckConstraint("code ~ '^[a-zA-Z0-9_-]{1,64}$'", name="ck_hr_dictionaries_code"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_hr_dictionaries_name"),
        Index("ix_hr_dictionaries_tenant_category", "tenant_id", "category", "sort_order"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
