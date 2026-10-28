"""工作流 ORM 模型：workflows 与 workflow_templates。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey

# user 端可见范围枚举值（与 Agent 保持一致，复用同一套可见性体系）
VISIBILITY_MODE_ALL = "all"
VISIBILITY_MODE_CUSTOM = "custom"


class WorkflowModel(Base):
    """workflows 表。"""

    __tablename__ = "workflows"
    __table_args__ = (
        CheckConstraint(
            "visibility_mode IN ('all', 'custom')",
            name="ck_workflows_visibility_mode",
        ),
        Index("ix_workflows_tenant_created_by", "tenant_id", "created_by"),
        # 同一租户下工作流名称唯一（忽略大小写）
        Index(
            "ux_workflows_tenant_name",
            "tenant_id",
            func.lower(text("name")),
            unique=True,
        ),
    )

    id: Mapped[UuidPrimaryKey]
    # tenant_id 非空：产品级工作流 = PLATFORM_TENANT_ID；租户工作流 = 真实租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # graph 为整图 JSON：{variables, nodes, edges, schema_version}
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # user 端可见范围：all=全员可见；custom=预留（MVP 不实现关联表）。
    visibility_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VISIBILITY_MODE_ALL
    )
    # 创建者（租户管理员 users.id），行级数据权限"本人创建"过滤依赖该列。
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkflowTemplateModel(Base):
    """workflow_templates 表：仅产品级使用，租户通过 clone 复制为自身 workflows。"""

    __tablename__ = "workflow_templates"
    __table_args__ = (
        CheckConstraint(
            "tenant_id = '00000000-0000-0000-0000-000000000000'",
            name="ck_workflow_templates_platform_only",
        ),
        # 模板名称全局唯一（产品级只有一个租户，等价于全表 lower(name) 唯一）
        Index(
            "ux_workflow_templates_platform_name",
            func.lower(text("name")),
            unique=True,
        ),
    )

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 模板分类：客服问答 / 数据查询 / 文档总结 等，便于模板市场分组
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
