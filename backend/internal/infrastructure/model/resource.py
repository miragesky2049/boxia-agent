"""技能、工具、组件、提示词 ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class SkillModel(Base):
    """skills 表。"""

    __tablename__ = "skills"
    __table_args__ = (Index("ix_skills_tenant_agent", "tenant_id", "agent_id"),)

    id: Mapped[UuidPrimaryKey]
    # NULL 表示产品级资源，所有租户可见；非空表示租户私有资源。
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    # 所属智能体；资源随智能体删除，NULL 表示尚未归属任何智能体。
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillFileModel(Base):
    """skill_files 表：技能包虚拟目录，平台级/租户级随所属 skill 隔离。"""

    __tablename__ = "skill_files"
    __table_args__ = (UniqueConstraint("skill_id", "path", name="ux_skill_files_path"),)

    id: Mapped[UuidPrimaryKey]
    skill_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/plain")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ToolModel(Base):
    """tools 表。"""

    __tablename__ = "tools"
    __table_args__ = (Index("ix_tools_tenant_agent", "tenant_id", "agent_id"),)

    id: Mapped[UuidPrimaryKey]
    # NULL 表示产品级资源，所有租户可见；非空表示租户私有资源。
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    # 所属智能体；资源随智能体删除，NULL 表示尚未归属任何智能体。
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="http")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ComponentModel(Base):
    """components 表。"""

    __tablename__ = "components"
    __table_args__ = (Index("ix_components_tenant_agent", "tenant_id", "agent_id"),)

    id: Mapped[UuidPrimaryKey]
    # NULL 表示产品级资源，所有租户可见；非空表示租户私有资源。
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    # 所属智能体；资源随智能体删除，NULL 表示尚未归属任何智能体。
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="card")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromptModel(Base):
    """prompts 表。"""

    __tablename__ = "prompts"
    __table_args__ = (Index("ix_prompts_tenant_agent", "tenant_id", "agent_id"),)

    id: Mapped[UuidPrimaryKey]
    # NULL 表示产品级资源，所有租户可见；非空表示租户私有资源。
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    # 所属智能体；资源随智能体删除，NULL 表示尚未归属任何智能体。
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
