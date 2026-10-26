"""部门领域实体：物化路径树，最多 10 级。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Department:
    """部门；parent_id 为空表示根部门，path 为 /<根id>/.../<自身id>/。"""

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
