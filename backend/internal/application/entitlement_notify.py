"""权益到期提醒用例：7/3/1 天分桶扫描 + 去重落审计（P3-2）。

通知管道当前形态：以 audit_logs 记录为站内可读的提醒载体，
去重键 (tenant_id, object_type, object_id, days) 用 detail.reminder_days
的 JSONB 包含查询实现；P3-7 取消开通通知复用本管道的记录方式。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from internal.application.audit import record_audit
from internal.domain.repository.apps_protocols import EntitlementRepositoryProtocol
from internal.domain.repository.protocols import UnitOfWork

EXPIRY_REMINDER_ACTION = "entitlement.expiry_reminder"
REMINDER_DAYS_BUCKETS = (7, 3, 1)


class EntitlementNotifyService:
    """到期提醒扫描编排：系统定时调用，自管提交。"""

    def __init__(
        self,
        uow: UnitOfWork,
        entitlement_repo: EntitlementRepositoryProtocol,
    ) -> None:
        self._uow = uow
        self._repo = entitlement_repo

    def scan_expiry_reminders(self, now: datetime) -> dict[str, int]:
        """按 7/3/1 天窗口扫描临期权益并写提醒记录，返回各桶实发数。"""
        sent: dict[str, int] = {}
        try:
            for days in REMINDER_DAYS_BUCKETS:
                rows = self._repo.list_expiring(now, days)
                count = 0
                for row in rows:
                    if self._already_sent(row, days):
                        continue
                    self._record(row, days, now)
                    count += 1
                sent[str(days)] = count
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return sent

    def _already_sent(self, row: dict[str, Any], days: int) -> bool:
        return self._uow.audit_logs.exists_with_detail(
            EXPIRY_REMINDER_ACTION,
            row["tenant_id"],
            str(row["object_type"]),
            str(row["object_id"]),
            {"reminder_days": days},
        )

    def _record(self, row: dict[str, Any], days: int, now: datetime) -> None:
        tenant_id: UUID = row["tenant_id"]
        record_audit(
            self._uow,
            action=EXPIRY_REMINDER_ACTION,
            actor_username="system",
            resource_type=str(row["object_type"]),
            resource_id=str(row["object_id"]),
            tenant_id=tenant_id,
            detail={
                "reminder_days": days,
                "tenant_id": str(tenant_id),
                "name": row["name"],
                "expire_time": row["expire_time"].isoformat() if row["expire_time"] else None,
                "scanned_at": now.isoformat(),
            },
        )
