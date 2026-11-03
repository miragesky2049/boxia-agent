"""Celery 定时任务：授权与资源权益状态流转。

- process_wait_effective: 每 5 分钟扫描 wait_effect → active（app 授权 + resource_grant）
- process_expired: 每 5 分钟扫描 active → expired（app 授权 + resource_grant）

beat 配置在 celery_app 中注册；资源权益复用同一调度，独立短事务（P3-1）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.auth.grant_service import GrantService
from internal.domain.auth.service import AuthService
from internal.domain.entity.request_context import PLATFORM_SCOPE, RequestContext
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository

logger = logging.getLogger(__name__)


def _run_process(kind: str) -> int:
    """同步执行 app 授权状态流转（DB 是同步 session，用 asyncio.run 包异步领域服务）。"""
    session_factory = get_session_factory()
    with session_factory() as session:
        repo = AuthRepository(session)
        auth_service = AuthService(repo, cache=None)
        grant_service = GrantService(repo, auth_service)
        if kind == "wait_effective":
            count = asyncio.run(grant_service.process_wait_effective())
        else:
            count = asyncio.run(grant_service.process_expired())
        session.commit()
        return count


def _run_resource_process(kind: str) -> int:
    """resource_grant 生命周期流转：与 app 授权分离的独立短事务（P3-1）。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        context = RequestContext(scope=PLATFORM_SCOPE, tenant=None, host="system")
        service = EntitlementService(uow, EntitlementRepository(uow.session), context)
        now = datetime.now(UTC)
        if kind == "wait_effective":
            count = service.process_resource_wait_effective(now)
        else:
            count = service.process_resource_expired(now)
        uow.commit()
        return count
    finally:
        uow.close()


@celery_app.task(name="auth.process_wait_effective")
def process_wait_effective_task() -> int:
    """定时：到点激活 wait_effect 授权与资源权益。"""
    grants = _run_process("wait_effective")
    resources = _run_resource_process("wait_effective")
    logger.info("wait_effective 任务完成，激活授权 %d 条、资源权益 %d 条", grants, resources)
    return grants + resources


@celery_app.task(name="auth.process_expired")
def process_expired_task() -> int:
    """定时：到期过期 active 授权与资源权益。"""
    grants = _run_process("expired")
    resources = _run_resource_process("expired")
    logger.info("expired 任务完成，过期授权 %d 条、资源权益 %d 条", grants, resources)
    return grants + resources
