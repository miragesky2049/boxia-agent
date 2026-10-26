"""管理单元领域实体：租户自定义业务单元树（物化路径，最多 10 级），并通过关联部门/人员形成数据权限容器。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

# 管理单元类型已收敛为单一 'unit'；保留常量便于代码内引用
MGMT_UNIT_TYPE = "unit"


@dataclass(frozen=True)
class ManagementUnit:
    """管理单元：作为数据权限容器，通过关联部门/人员决定其能看到哪些智能体。"""

    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    name: str
    code: str | None
    path: str
    level: int
    sort_order: int
    attrs: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MgmtUnitDepartment:
    """管理单元关联部门；include_subtree 为 True 时包含该部门全部下级。"""

    unit_id: UUID
    department_id: UUID
    include_subtree: bool


@dataclass(frozen=True)
class MgmtUnitUser:
    """管理单元关联人员（直接关联的人员 id）。"""

    unit_id: UUID
    user_id: UUID
