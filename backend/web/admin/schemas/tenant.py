"""租户、作用域与密码策略模型。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from internal.infrastructure.config.settings import Settings

AppEnv = Literal["local", "dev", "test", "prod"]
TenantResolution = Literal["host", "header", "default"]
TenantSwitchMode = Literal["none", "header", "host"]


class TenantOut(BaseModel):
    """租户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantCreateRequest(BaseModel):
    """创建租户请求，同时初始化租户级超级管理员。"""

    code: str = Field(min_length=1, max_length=63)
    name: str = Field(min_length=1, max_length=100)
    admin_username: str = Field(min_length=3, max_length=64)
    admin_password: str = Field(min_length=1, max_length=128)
    admin_display_name: str = Field(default="", max_length=64)


class TenantUpdateRequest(BaseModel):
    """更新租户请求。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class TenantDeleteOut(BaseModel):
    """单租户删除结果。"""

    tenant_id: UUID
    code: str
    audit_id: UUID
    deleted: dict[str, int] = Field(default_factory=dict)


class TenantBatchDeleteRequest(BaseModel):
    """批量删除租户请求；confirm 必须显式传 true。"""

    tenant_ids: list[UUID] = Field(min_length=1, max_length=100)
    confirm: bool = False
    reason: str = Field(default="", max_length=200)


class TenantBatchDeleteItemOut(BaseModel):
    """批量删除单项结果。"""

    tenant_id: UUID
    code: str | None = None
    success: bool
    audit_id: UUID | None = None
    error_code: str | None = None
    error: str | None = None


class TenantBatchDeleteOut(BaseModel):
    """批量删除汇总结果（部分成功时 HTTP 仍为 200）。"""

    total: int
    succeeded: int
    failed: int
    items: list[TenantBatchDeleteItemOut]


class PasswordPolicyOut(BaseModel):
    """密码策略，前端表单与后端校验共用同一份配置。"""

    min_length: int
    max_bytes: int
    min_categories: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "PasswordPolicyOut":
        """从进程配置构造，避免各接口重复映射字段。"""
        return cls(
            min_length=settings.password_min_length,
            max_bytes=settings.password_max_bytes,
            min_categories=settings.password_min_categories,
        )
