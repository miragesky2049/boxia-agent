"""管理单元请求/响应模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MgmtUnitOut(BaseModel):
    """管理单元节点，children 由 Web 层按物化路径组装。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    name: str
    code: str | None
    path: str
    level: int
    sort_order: int
    attrs: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime
    children: list["MgmtUnitOut"] = Field(default_factory=list)


class MgmtUnitCreateRequest(BaseModel):
    """创建管理单元请求。"""

    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=999999)
    attrs: dict[str, Any] = Field(default_factory=dict)


class MgmtUnitUpdateRequest(BaseModel):
    """更新管理单元请求，parent_id 变化触发子树移动。"""

    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=999999)
    attrs: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class MgmtUnitDepartmentOut(BaseModel):
    """管理单元关联部门项。"""

    model_config = ConfigDict(from_attributes=True)

    unit_id: UUID
    department_id: UUID
    include_subtree: bool


class MgmtUnitDepartmentBinding(BaseModel):
    """管理单元关联部门写入项。"""

    department_id: UUID
    include_subtree: bool = False


class MgmtUnitDepartmentsReplaceRequest(BaseModel):
    """整体替换管理单元部门关联请求。"""

    bindings: list[MgmtUnitDepartmentBinding] = Field(default_factory=list)


class MgmtUnitUserOut(BaseModel):
    """管理单元关联人员项。"""

    model_config = ConfigDict(from_attributes=True)

    unit_id: UUID
    user_id: UUID


class MgmtUnitUsersReplaceRequest(BaseModel):
    """整体替换管理单元人员关联请求。"""

    user_ids: list[UUID] = Field(default_factory=list)
