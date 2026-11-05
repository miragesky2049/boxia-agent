"""审计日志的 PostgreSQL 仓储实现。"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.entity.audit_log import AuditLog
from internal.infrastructure.model.audit_log import AuditLogModel


def _json_safe(value: Any) -> Any:
    """把 UUID 等非 JSON 原生类型转换为字符串，审计明细可携带资源 ID。"""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


class PostgresAuditLogRepository:
    """基于 SQLAlchemy 的审计日志仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def record(self, values: dict[str, Any]) -> UUID:
        """写入审计记录并返回记录 ID（调用方负责提交；purge 快照需回填 audit_id，P3-6）。"""
        payload = dict(values)
        # JSONB 列由 psycopg 用标准 json 序列化，UUID 需先转为字符串
        payload["detail"] = _json_safe(payload.get("detail"))
        model = AuditLogModel(**payload)
        self._session.add(model)
        self._session.flush()
        return model.id

    def list_page(
        self,
        page: int,
        page_size: int,
        action: str | None,
        actor_id: UUID | None,
        tenant_id: UUID | None = None,
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

    def exists_with_detail(
        self,
        action: str,
        tenant_id: UUID,
        resource_type: str,
        resource_id: str,
        detail: dict[str, Any],
    ) -> bool:
        """JSONB 包含判定（@>），用于到期提醒等系统记录的去重键查询（P3-2）。"""
        found = self._session.scalar(
            select(AuditLogModel.id)
            .where(
                AuditLogModel.action == action,
                AuditLogModel.tenant_id == tenant_id,
                AuditLogModel.resource_type == resource_type,
                AuditLogModel.resource_id == resource_id,
                AuditLogModel.detail.contains(detail),
            )
            .limit(1)
        )
        return found is not None

    def delete_all(self, tenant_id: UUID | None = None) -> int:
        """清空审计日志；tenant_id 非空时只清该租户，否则清空全部（平台级）。"""
        stmt = delete(AuditLogModel)
        if tenant_id is not None:
            stmt = stmt.where(AuditLogModel.tenant_id == tenant_id)
        result = cast(CursorResult[Any], self._session.execute(stmt))
        self._session.flush()
        return int(result.rowcount or 0)

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
