"""租户 ORM 模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class TenantModel(Base):
    """tenants 表：租户编码即子域名前缀。"""

    __tablename__ = "tenants"

    id: Mapped[UuidPrimaryKey]
    code: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
