"""工具领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID

# 资源审核状态（迁移 0056 ck_resource_review_status 三值）：
# 平台自建直接 approved，租户自建进入 pending 走人工审核。
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUSES = (REVIEW_STATUS_PENDING, REVIEW_STATUS_APPROVED, REVIEW_STATUS_REJECTED)


@dataclass(frozen=True)
class Tool:
    """工具。"""

    id: UUID
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id == PLATFORM_TENANT_ID
