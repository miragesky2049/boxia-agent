"""工具领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID


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
