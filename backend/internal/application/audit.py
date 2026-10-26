"""审计记录写入辅助。"""

from typing import Any
from uuid import UUID

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
) -> None:
    """写入一条审计记录（与调用方共享事务）。"""
    uow.audit_logs.record(
        {
            "tenant_id": tenant_id,
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
