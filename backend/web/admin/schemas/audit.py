"""审计日志响应模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    """审计日志出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    actor_username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    request_id: str | None
    ip: str | None
    user_agent: str | None
    detail: dict[str, Any]
    tenant_id: UUID | None = None
    created_at: datetime
