"""审计日志领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AuditLog:
    """管理端操作审计记录。"""

    id: UUID
    actor_id: UUID | None
    actor_username: str
    action: str
    resource_type: str
    resource_id: str
    request_id: str | None
    ip: str | None
    user_agent: str | None
    detail: dict[str, Any]
    created_at: datetime
    tenant_id: UUID | None = None
