"""统一资源 ORM 模型（resource 表）。

type 区分 tool / prompt / skill / knowledge；owner_type + owner_id 标识归属：
owner_type='platform' 表示产品级资源（owner_id 为空），owner_type='tenant' 时
owner_id 为所属租户 ID。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class ResourceModel(Base):
    """resource 表：统一资源库，按 type 列区分资源类别。"""

    __tablename__ = "resource"

    id: Mapped[UuidPrimaryKey]
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="approved",
        comment="pending / approved / rejected",
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), comment="审核人")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="审核时间"
    )
    review_remark: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="", comment="审核意见"
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), comment="创建人（职责分离校验用，历史存量 NULL）"
    )


class ResourceEntitlementModel(Base):
    """resource_grant 单表：租户对资源的权益行（运营开通/市场申请落此表）。

    与复数 resource_grants（角色授权，"哪些角色可用"）职责不同：单表表达
    "租户是否已开通权益"。本模型仅供读侧 EXISTS 判定装配（P1-8），
    写路径仍走 EntitlementRepository 裸 SQL。
    """

    __tablename__ = "resource_grant"

    id: Mapped[UuidPrimaryKey]
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expire_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
