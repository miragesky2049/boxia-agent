"""用户任职记录领域实体。"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True)
class Employment:
    """任职记录；is_current 为真时对应用户的当前主任职，同一用户同时仅一条。"""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    department_id: UUID
    position: str
    is_current: bool
    started_at: date
    ended_at: date | None
    created_at: datetime
    updated_at: datetime
    # 列表展示用冗余字段，由仓储 join 用户/部门填充
    user_name: str | None = None
    user_display_name: str | None = None
    department_name: str | None = None
    department_path: str | None = None
