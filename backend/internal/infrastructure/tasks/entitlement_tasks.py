"""Celery 定时任务：权益到期提醒（P3-2）与宽限期流转（P3-11）。

- scan_expiry_reminders: 每天扫描 7/3/1 天内到期的权益并写提醒记录（去重键含 days）
- process_grace_revoked: 每天把宽限期超期的 expired 行落库为 revoked

beat 配置在 celery_app 中注册。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from internal.application.apps.entitlement_service import EntitlementService
from internal.application.entitlement_notify import EntitlementNotifyService
from internal.domain.entity.request_context import PLATFORM_SCOPE, RequestContext
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.config.settings import get_settings
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


@celery_app.task(name="entitlement.process_grace_revoked")
def process_grace_revoked_task() -> int:
    """定时：宽限期超期流转，把 grace_days 窗口外仍为 expired 的权益行持久化为 revoked。"""
    grace_days = get_settings().entitlement_grace_days
    if grace_days <= 0:
        return 0
    uow = SqlAlchemyUnitOfWork()
    try:
        context = RequestContext(scope=PLATFORM_SCOPE, tenant=None, host="system")
        service = EntitlementService(
            uow,
            EntitlementRepository(uow.session),
            context,
            grace_days=grace_days,
        )
        count = service.process_grace_revoked(datetime.now(UTC))
        uow.commit()
    finally:
        uow.close()
    logger.info("宽限期流转完成，expired→revoked %d 条（grace_days=%d）", count, grace_days)
    return count
