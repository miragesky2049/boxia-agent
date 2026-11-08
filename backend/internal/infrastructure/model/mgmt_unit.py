"""管理单元 ORM 模型：物化路径树 + 部门/人员关联表。"""

from datetime import datetime
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey

# 永不会被应用层 UUID v7 分配的 nil UUID，用于在唯一索引中占位 NULL 父单元。
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


class MgmtUnitModel(Base):
    """mgmt_units 表：租户自定义业务单元；作为数据权限容器通过部门/人员关联决定可见范围。"""

    __tablename__ = "mgmt_units"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 10", name="ck_mgmt_units_level"),
        CheckConstraint("(parent_id IS NULL) = (level = 1)", name="ck_mgmt_units_root"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_mgmt_units_name"),
        CheckConstraint(
            "code IS NULL OR (code = lower(code) AND code ~ '^[a-z0-9_-]{1,64}$')",
            name="ck_mgmt_units_code",
        ),
        CheckConstraint(
            "path = '/' || id::text || '/' OR path LIKE '%/' || id::text || '/'",
            name="ck_mgmt_units_path_shape",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_mgmt_units_tenant_id"),
        UniqueConstraint("tenant_id", "path", name="uq_mgmt_units_tenant_path"),
        Index(
            "ux_mgmt_units_tenant_code",
            "tenant_id",
            func.lower(text("code")),
            unique=True,
        ),
        Index(
            "ux_mgmt_units_parent_name",
            "tenant_id",
            func.coalesce(text("parent_id"), text(f"'{_NIL_UUID}'::uuid")),
            func.lower(text("name")),
            unique=True,
        ),
        Index("ix_mgmt_units_tenant_parent", "tenant_id", "parent_id"),
        Index(
            "ix_mgmt_units_tenant_path",
            "tenant_id",
            "path",
            postgresql_ops={"path": "text_pattern_ops"},
        ),
        Index("ix_mgmt_units_tenant_type", "tenant_id", "is_active"),
        Index("ix_mgmt_units_tenant_sort", "tenant_id", "parent_id", "sort_order", "id"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mgmt_units.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MgmtUnitDepartmentModel(Base):
    """mgmt_unit_departments 表：管理单元关联部门（含子树开关）。"""

    __tablename__ = "mgmt_unit_departments"
    __table_args__ = (Index("ix_mud_department", "department_id"),)

    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mgmt_units.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    include_subtree: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MgmtUnitUserModel(Base):
    """mgmt_unit_users 表：管理单元关联人员。"""

    __tablename__ = "mgmt_unit_users"
    __table_args__ = (Index("ix_muu_user", "user_id"),)

    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mgmt_units.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
