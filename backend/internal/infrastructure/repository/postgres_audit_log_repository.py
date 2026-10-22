"""审计日志的 PostgreSQL 仓储实现。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from internal.domain.entity.audit_log import AuditLog
from internal.infrastructure.model.audit_log import AuditLogModel


class PostgresAuditLogRepository:
    """基于 SQLAlchemy 的审计日志仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def record(self, values: dict[str, Any]) -> None:
        """写入审计记录（调用方负责提交）。"""
        self._session.add(AuditLogModel(**values))
        self._session.flush()

    def list_page(
        self,
        page: int,
        page_size: int,
        action: str | None,
        actor_id: int | None,
        tenant_id: int | None = None,
    ) -> tuple[list[AuditLog], int]:
        """分页查询审计记录；tenant_id 非空时只查该租户。"""
        stmt = select(AuditLogModel)
        if tenant_id is not None:
            stmt = stmt.where(AuditLogModel.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLogModel.action == action)
        if actor_id is not None:
            stmt = stmt.where(AuditLogModel.actor_id == actor_id)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], int(total)

    @staticmethod
    def _to_entity(row: AuditLogModel) -> AuditLog:
        return AuditLog(
            id=row.id,
            actor_id=row.actor_id,
            actor_username=row.actor_username,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            request_id=row.request_id,
            ip=row.ip,
            user_agent=row.user_agent,
            detail=row.detail or {},
            created_at=row.created_at,
            tenant_id=row.tenant_id,
        )
