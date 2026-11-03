"""角色授权明细请求/响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoleGrantResourceOut(BaseModel):
    """角色授权资源项。"""

    model_config = ConfigDict(from_attributes=True)

    resource_id: UUID
    name: str
    description: str
    is_platform: bool
    is_enabled: bool
    updated_at: datetime
    is_granted: bool
    is_tenant_wide: bool = False


class RoleGrantReplaceRequest(BaseModel):
    """整体替换角色授权；空数组表示清空该类资源授权。"""

    resource_ids: list[UUID] = Field(default_factory=list)


class RoleGrantAddRequest(BaseModel):
    """追加角色授权。"""

    resource_ids: list[UUID] = Field(min_length=1)


class RoleGrantUpdateOut(BaseModel):
    """角色授权变更结果。"""

    updated: int


class RoleGrantSummaryOut(BaseModel):
    """角色有效授权汇总，按资源类型返回数量。"""

    counts: dict[str, int] = Field(default_factory=dict)
