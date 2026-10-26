"""部门请求/响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DepartmentOut(BaseModel):
    """部门节点，children 由 Web 层按物化路径组装。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    name: str
    code: str | None
    path: str
    level: int
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    children: list["DepartmentOut"] = Field(default_factory=list)


class DepartmentCreateRequest(BaseModel):
    """创建部门请求。"""

    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=999999)
    is_active: bool = True


class DepartmentUpdateRequest(BaseModel):
    """更新部门请求，parent_id 变化触发子树移动（根部门为空）。"""

    parent_id: UUID | None
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=999999)


class DepartmentActiveRequest(BaseModel):
    """停用/启用部门请求。"""

    is_active: bool
