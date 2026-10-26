"""用户被授权的管理单元（数据权限授权）实体。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class UserMgmtUnitGrant:
    """租户用户被授权使用的管理单元；同一用户同一单元至多一条。"""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    unit_id: UUID
    granted_by: UUID | None
    created_at: datetime
