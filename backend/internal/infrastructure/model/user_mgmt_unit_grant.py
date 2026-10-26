"""用户被授权的管理单元 ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class UserMgmtUnitGrantModel(Base):
    """user_mgmt_unit_grants 表：租户用户被授权使用的管理单元（行级数据权限授权）。"""

    __tablename__ = "user_mgmt_unit_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_umug_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["mgmt_units.tenant_id", "mgmt_units.id"],
            name="fk_umug_unit",
            ondelete="CASCADE",
        ),
        Index("ix_umug_user", "tenant_id", "user_id"),
        Index("ix_umug_unit", "tenant_id", "unit_id"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # 授权人可能是平台管理员（admin_users）或租户账号（users），无法用单一外键约束
    granted_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
