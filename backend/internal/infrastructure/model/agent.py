"""智能体 ORM 模型与关联表。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey

# user 端可见范围枚举值
VISIBILITY_MODE_ALL = "all"
VISIBILITY_MODE_CUSTOM = "custom"

agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column(
        "agent_id",
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tool_id", Uuid(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True
    ),
)

agent_skills = Table(
    "agent_skills",
    Base.metadata,
    Column(
        "agent_id",
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "skill_id",
        Uuid(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class AgentModel(Base):
    """agents 表。"""

    __tablename__ = "agents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_agents_department",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"tenant_id <> '00000000-0000-0000-0000-000000000000' OR department_id IS NULL",
            name="ck_agents_platform_no_dept",
        ),
        # 租户智能体所属部门必填：行级数据权限（按部门过滤）依赖该列
        CheckConstraint(
            f"tenant_id = '00000000-0000-0000-0000-000000000000' OR department_id IS NOT NULL",
            name="ck_agents_tenant_dept_required",
        ),
        CheckConstraint(
            f"visibility_mode IN ('{VISIBILITY_MODE_ALL}', '{VISIBILITY_MODE_CUSTOM}')",
            name="ck_agents_visibility_mode",
        ),
        Index("ix_agents_tenant_department", "tenant_id", "department_id"),
        Index("ix_agents_tenant_created_by", "tenant_id", "created_by"),
    )

    id: Mapped[UuidPrimaryKey]
    # tenant_id 非空：产品级智能体 = PLATFORM_TENANT_ID（全零 UUID）；租户智能体 = 真实租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 归属部门仅租户智能体可填，平台智能体必须为空；租户智能体必填（行级权限依赖）。
    department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # 创建者（租户管理员 users.id），行级数据权限"本人创建"过滤依赖该列。
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # user 端可见范围：all=全员可见（默认）；custom=按 agent_visibility_* 关联表过滤。
    visibility_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VISIBILITY_MODE_ALL
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentTenantOpeningModel(Base):
    """agent_tenant_openings 表：平台智能体对租户的开通关系。"""

    __tablename__ = "agent_tenant_openings"
    __table_args__ = (
        UniqueConstraint("agent_id", "tenant_id", name="ux_agent_tenant_openings"),
        Index("ix_agent_tenant_openings_tenant", "tenant_id", "agent_id"),
    )

    id: Mapped[UuidPrimaryKey]
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    opened_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentVisibilityDepartmentModel(Base):
    """agent_visibility_departments 表：智能体 user 端可见部门（含子树开关）。"""

    __tablename__ = "agent_visibility_departments"
    __table_args__ = (
        Index("ix_avd_department", "department_id"),
    )

    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    include_subtree: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentVisibilityUserModel(Base):
    """agent_visibility_users 表：智能体 user 端可见人员。"""

    __tablename__ = "agent_visibility_users"
    __table_args__ = (
        Index("ix_avu_user", "user_id"),
    )

    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
