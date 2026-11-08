"""长期记忆 ORM 模型：agent_memory 表（M4 PRD F16.2）。

表结构与 0077 迁移对齐；embedding 列不建（F16.5 开工时 ALTER + 回填）。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey

MEMORY_KINDS = ("preference", "fact", "episode")
MEMORY_STATUSES = ("active", "archived")


class AgentMemoryModel(Base):
    """agent_memory 表：用户 × 应用维度的跨会话长期记忆条目。"""

    __tablename__ = "agent_memory"
    __table_args__ = (
        Index("ix_agent_memory_scope", "tenant_id", "application_id", "user_id", "status"),
        CheckConstraint("kind IN ('preference', 'fact', 'episode')", name="ck_agent_memory_kind"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_agent_memory_status"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    # PRD F16.2：user_id 不建外键——用户注销后记忆随租户级联清理即可，行本身可溯来源 run
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
