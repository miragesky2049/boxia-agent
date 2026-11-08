"""应用授权相关 ORM：基于现有表扩展字段。

复用策略：
- application（原 app_def）：加 sale_mode / support_trial / doc_url / ext_json
- tenant_application_instance（原 tenant_app_auth）：加 auth_type / contract_no / quota_json / start_time / expire_time / apply_id
- audit_logs（原 auth_operation_log）：直接复用，action 字段存操作枚举，detail 存 before/after snapshot
- application_apply（新建）：申请单表，没有现成表可复用
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


# ========== 复用 application 表：授权相关扩展字段 ==========
class ApplicationAuthMixin:
    """application 表的授权扩展字段（与 application 主表一对一直挂）。

    实际项目中这些字段直接加到 application 表上，这里用 mixin 表达语义。
    """

    sale_mode: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
        comment="1=仅运营后台开通；2=市场可见+可申请",
    )
    support_trial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    doc_url: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    ext_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'",
    )


# ========== 复用 tenant_application_instance 表：授权扩展字段 ==========
class TenantAppAuthModel(Base):
    """tenant_application_instance 表：租户对应用的授权记录。

    已有字段（0029 迁移）：
    - id / tenant_id / application_id / status / source / overrides / pinned_version
    - granted_by / granted_at / created_at / updated_at

    新增字段（本次授权 MVP）：
    - auth_type / contract_no / quota_json / start_time / expire_time / apply_id / remark / auth_source
    """

    __tablename__ = "tenant_application_instance"

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="active",
        comment="active / suspended / disabled / revoked / wait_effect / expired",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="marketplace",
        comment="marketplace / granted",
    )
    # 新增：授权来源（OPS / MARKET_APPLY）
    auth_source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="OPS",
        comment="OPS=运营直接开通；MARKET_APPLY=市场申请单关联开通",
    )
    # 新增：授权类型（FORMAL / TRIAL / GIFT）
    auth_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="FORMAL",
    )
    # 新增：合同号
    contract_no: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default="",
    )
    # 新增：配额 JSON
    quota_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'",
    )
    # 新增：生效/到期时间
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expire_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 新增：关联申请单 ID
    apply_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )
    # 新增：备注
    remark: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    granted_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ========== 新建 application_apply 表：租户申请单 ==========
class ApplicationApplyModel(Base):
    """application_apply 表：租户对应用的申请单。"""

    __tablename__ = "application_apply"

    id: Mapped[UuidPrimaryKey]
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    apply_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="TRIAL / BUY",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="SUBMITTED",
        comment="SUBMITTED / HANDLING / PASS / REJECT / FINISH",
    )
    expect_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    contact: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        server_default="",
    )
    sales_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )
    audit_msg: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    contract_no: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default="",
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
