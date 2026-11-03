"""审计记录写入辅助。"""

from typing import Any
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.repository.protocols import UnitOfWork


def record_audit(
    uow: UnitOfWork,
    action: str,
    actor_id: UUID | None = None,
    actor_username: str = "",
    resource_type: str = "",
    resource_id: str = "",
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
    tenant_id: UUID | None = None,
) -> UUID:
    """写入一条审计记录并返回记录 ID（与调用方共享事务）；平台操作默认归属 PLATFORM_TENANT_ID。"""
    return uow.audit_logs.record(
        {
            "tenant_id": tenant_id if tenant_id is not None else PLATFORM_TENANT_ID,
            "actor_id": actor_id,
            "actor_username": actor_username,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "ip": ip,
            "user_agent": user_agent,
            "detail": detail or {},
        }
    )
