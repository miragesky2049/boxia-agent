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
CHANGE_NOTICE_ACTION = "entitlement.change_notice"
NOTICE_MODE_REVOKED = "revoked"
NOTICE_MODE_RESTORED = "restored"
REMINDER_DAYS_BUCKETS = (7, 3, 1)


def record_change_notice(
    uow: UnitOfWork,
    *,
    tenant_id: UUID,
    object_type: str,
    object_id: str,
    name: str,
    notice_mode: str,
    reason: str,
    actor_username: str,
    operated_at: datetime,
) -> None:
    """取消/恢复开通通知：复用到期提醒的审计载体管道，归属被通知租户（P3-7）。

    与批量操作共享同一事务：批量回滚则通知不落库；重放会重复通知，
    P3-8 幂等层落地后由 request_id 去重收口。
    """
    record_audit(
        uow,
        action=CHANGE_NOTICE_ACTION,
        actor_username=actor_username,
        resource_type=object_type,
        resource_id=object_id,
        tenant_id=tenant_id,
        detail={
            "notice_mode": notice_mode,
            "tenant_id": str(tenant_id),
            "object_type": object_type,
            "object_id": object_id,
            "name": name,
            "reason": reason,
            "operated_by": actor_username,
            "operated_at": operated_at.isoformat(),
        },
    )


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
