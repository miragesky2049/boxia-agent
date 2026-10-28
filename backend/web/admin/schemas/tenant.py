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


class TenantAgentOut(BaseModel):
    """租户详情页的产品智能体及其开通状态。"""

    id: UUID
    name: str
    avatar_url: str
    description: str
    is_enabled: bool
    is_opened: bool
    opened_at: datetime | None = None
    opened_by: UUID | None = None


class TenantAgentOpenRequest(BaseModel):
    """开通或关闭租户对产品智能体的访问。"""

    opened: bool


class TenantAgentOpenOut(BaseModel):
    """开通/关闭操作结果。"""

    agent_id: UUID
    tenant_id: UUID
    is_opened: bool
    opened_at: datetime | None = None


class TenantAgentBatchOpenRequest(BaseModel):
    """批量开通或关闭租户对产品智能体的访问。"""

    agent_ids: list[UUID] = Field(min_length=1, max_length=100)
    opened: bool


class TenantAgentBatchOpenOut(BaseModel):
    """批量开通/关闭操作结果。"""

    tenant_id: UUID
    opened: bool
    count: int
    agent_ids: list[UUID]


class AgentOpenedTenantOut(BaseModel):
    """智能体详情页展示的已开通租户。"""

    id: UUID
    code: str
    name: str
    is_active: bool
    opened_at: datetime
    opened_by: UUID | None = None


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
