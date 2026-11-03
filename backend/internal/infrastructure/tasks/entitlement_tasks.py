"""Celery 定时任务：权益到期提醒（P3-2）。

- scan_expiry_reminders: 每天扫描 7/3/1 天内到期的权益并写提醒记录（去重键含 days）

beat 配置在 celery_app 中注册。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from internal.application.entitlement_notify import EntitlementNotifyService
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository

logger = logging.getLogger(__name__)


@celery_app.task(name="entitlement.scan_expiry_reminders")
def scan_expiry_reminders_task() -> dict[str, int]:
    """定时：临期权益提醒扫描，返回各桶实发数。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        service = EntitlementNotifyService(uow, EntitlementRepository(uow.session))
        sent = service.scan_expiry_reminders(datetime.now(UTC))
    finally:
        uow.close()
    logger.info("到期提醒任务完成，各桶实发 %s", sent)
    return sent
