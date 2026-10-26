"""部门 ORM 模型：物化路径树，最多 10 级。"""

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
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey

# 永不会被应用层 UUID v7 分配的 nil UUID，用于在唯一索引中占位 NULL 父部门。
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


class DepartmentModel(Base):
    """departments 表。"""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_departments_tenant_id"),
        UniqueConstraint("tenant_id", "path", name="uq_departments_tenant_path"),
        CheckConstraint("level BETWEEN 1 AND 10", name="ck_departments_level"),
        CheckConstraint("(parent_id IS NULL) = (level = 1)", name="ck_departments_root"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_departments_name"),
        CheckConstraint(
            "code IS NULL OR (code = lower(code) "
            "AND code ~ '^[a-z0-9_-]{1,64}$')",
            name="ck_departments_code",
        ),
        CheckConstraint(
            "path = '/' || id::text || '/' OR path LIKE '%/' || id::text || '/'",
            name="ck_departments_path_shape",
        ),
        CheckConstraint("char_length(path) <= 400", name="ck_departments_path_len"),
        Index(
            "ux_departments_tenant_code",
            "tenant_id",
            func.lower(text("code")),
            unique=True,
        ),
        Index(
            "ux_departments_parent_name",
            "tenant_id",
            func.coalesce(text("parent_id"), text(f"'{_NIL_UUID}'::uuid")),
            func.lower(text("name")),
            unique=True,
        ),
        Index("ix_departments_tenant_parent", "tenant_id", "parent_id"),
        Index(
            "ix_departments_tenant_path",
            "tenant_id",
            "path",
            postgresql_ops={"path": "text_pattern_ops"},
        ),
        Index("ix_departments_tenant_sort", "tenant_id", "parent_id", "sort_order", "id"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
