"""租户角色、最终用户与资源授权 ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base

RESOURCE_TYPES = ("agent", "skill", "tool", "component", "prompt")


class RoleModel(Base):
    """roles 表：tenant_id 为空表示平台角色，非空表示租户角色。"""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="ux_roles_tenant_code"),
        # 复合外键需要被引用列上有唯一约束
        UniqueConstraint("id", "tenant_id", name="ux_roles_id_tenant"),
        CheckConstraint(
            "system_role IN ('superadmin', 'admin', 'viewer')",
            name="ck_roles_system_role",
        ),
        Index("ix_roles_tenant_active", "tenant_id", "is_active"),
        Index(
            "ux_roles_platform_code",
            func.lower(text("code")),
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "ux_roles_platform_name",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserModel(Base):
    """users 表：租户最终用户，绑定租户角色。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="ux_users_tenant_username"),
        ForeignKeyConstraint(
            ["role_id", "tenant_id"],
            ["roles.id", "roles.tenant_id"],
            name="fk_users_role_tenant",
            ondelete="RESTRICT",
        ),
        Index("ix_users_tenant_role", "tenant_id", "role_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserRoleModel(Base):
    """user_roles 表：用户与租户角色的多对多关联。"""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="ux_user_roles_user_role"),
        ForeignKeyConstraint(
            ["role_id", "tenant_id"],
            ["roles.id", "roles.tenant_id"],
            name="fk_user_roles_role_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_user_roles_role", "tenant_id", "role_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRefreshTokenModel(Base):
    """user_refresh_tokens 表：仅保存哈希，轮换与重放检测同管理员会话。"""

    __tablename__ = "user_refresh_tokens"
    __table_args__ = (
        Index("ix_user_refresh_tokens_user_id", "user_id"),
        Index("ix_user_refresh_tokens_family_id", "family_id"),
        Index("ix_user_refresh_tokens_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(BigInteger)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class ResourceGrantModel(Base):
    """resource_grants 表：资源对租户或租户角色的授权。

    role_id 为空表示授予整个租户；非空表示仅授予该租户的指定角色。
    """

    __tablename__ = "resource_grants"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('agent', 'skill', 'tool', 'component', 'prompt')",
            name="ck_resource_grants_type",
        ),
        CheckConstraint(
            "tenant_id IS NOT NULL OR role_id IS NOT NULL",
            name="ck_resource_grants_scope",
        ),
        ForeignKeyConstraint(
            ["role_id", "tenant_id"],
            ["roles.id", "roles.tenant_id"],
            name="fk_resource_grants_role_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_resource_grants_resource", "resource_type", "resource_id"),
        Index("ix_resource_grants_tenant_role", "tenant_id", "resource_type", "role_id"),
        Index(
            "ux_resource_grants_tenant_wide",
            "resource_type",
            "resource_id",
            "tenant_id",
            unique=True,
            postgresql_where=text("role_id IS NULL"),
        ),
        Index(
            "ux_resource_grants_role",
            "resource_type",
            "resource_id",
            "tenant_id",
            "role_id",
            unique=True,
            postgresql_where=text("role_id IS NOT NULL"),
        ),
        Index(
            "ux_resource_grants_platform_role",
            "resource_type",
            "resource_id",
            "role_id",
            unique=True,
            postgresql_where=text("tenant_id IS NULL AND role_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE")
    )
    granted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
