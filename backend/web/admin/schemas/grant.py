"""资源授权请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GrantOut(BaseModel):
    """单条资源授权；role_id 为空表示授予整个租户。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_type: str
    resource_id: int
    tenant_id: int
    role_id: int | None = None
    granted_by: int | None = None
    created_at: datetime


class GrantInput(BaseModel):
    """授权项入参。"""

    tenant_id: int = Field(ge=1)
    role_id: int | None = Field(default=None, ge=1)


class GrantReplaceRequest(BaseModel):
    """整体替换资源授权请求。"""

    grants: list[GrantInput] = Field(default_factory=list)


class GrantOverviewOut(BaseModel):
    """授权管理列表项：资源基础信息 + 授权汇总。"""

    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    name: str
    description: str
    is_platform: bool
    is_enabled: bool
    updated_at: datetime
    grant_count: int
    tenant_count: int
    role_count: int


class GrantBatchRequest(BaseModel):
    """批量授权请求；role_ids 为空表示整个租户（仅平台视角）。"""

    resource_type: str = Field(max_length=16)
    resource_ids: list[int] = Field(min_length=1, max_length=100)
    mode: Literal["merge", "replace", "clear"]
    tenant_id: int | None = Field(default=None, ge=1)
    role_ids: list[int] = Field(default_factory=list)


class GrantBatchOut(BaseModel):
    """批量授权结果。"""

    updated: int


class UserRoleGrantRequest(BaseModel):
    """批量给用户授予角色请求。"""

    user_ids: list[int] = Field(min_length=1, max_length=200)
    role_ids: list[int] = Field(min_length=1, max_length=50)
    tenant_id: int | None = Field(default=None, ge=1)
