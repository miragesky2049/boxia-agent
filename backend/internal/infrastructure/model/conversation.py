"""会话与消息 ORM 模型：user 端 chat 多轮对话持久化。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class ConversationModel(Base):
    """conversation 表：一次用户会话（用户 + 应用维度）。"""

    __tablename__ = "conversation"
    __table_args__ = (
        Index("ix_conversation_user", "tenant_id", "user_id", "updated_at"),
        Index("ix_conversation_channel_user", "tenant_id", "user_id", "channel", "updated_at"),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # 迁移 0044 建表时未对 user_id 建外键（用户删除由应用层 purge 清理会话），
    # 模型与库保持一致，避免 alembic check 误报需要补 FK。
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # M4 PRD F14.9：接管路由态（active NULL=归属应用应答；目标应用删除时 SET NULL 自动归位）
    active_application_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("application.id", ondelete="SET NULL")
    )
    # 接管顺序应用 id 数组（归属应用为首元素），判定见 domain/agent/handoff
    handoff_chain: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    # M4 PRD F15.2：摘要式记忆三列（不落 message 行，防污染消息面与前端历史渲染）
    summary: Mapped[str | None] = mapped_column(Text)
    summary_through_message_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageModel(Base):
    """message 表：会话内单条消息（user / assistant / tool / system）。"""

    __tablename__ = "message"
    __table_args__ = (Index("ix_message_conversation", "conversation_id", "created_at"),)

    id: Mapped[UuidPrimaryKey]
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    tool_call_id: Mapped[str | None] = mapped_column(String(100))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("run.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
