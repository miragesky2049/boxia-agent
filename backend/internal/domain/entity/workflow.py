"""工作流领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID


@dataclass(frozen=True)
class Workflow:
    """工作流：DAG 整图存 graph JSONB，MVP 不落运行历史。"""

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    graph: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    # 创建者（租户管理员 users.id），行级数据权限"本人创建"过滤依赖该列
    created_by: UUID | None = None
    # user 端可见范围：all=全员可见；custom=预留（MVP 不实现关联表）
    visibility_mode: str = "all"

    @property
    def is_platform(self) -> bool:
        """是否为产品级工作流（所有租户可见、仅产品级平台可维护）。"""
        return self.tenant_id == PLATFORM_TENANT_ID


@dataclass(frozen=True)
class WorkflowTemplate:
    """工作流模板：仅产品级维护，租户一键复制为自身 Workflow。"""

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    graph: dict[str, Any]
    category: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
