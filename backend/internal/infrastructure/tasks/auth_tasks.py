"""Celery 定时任务：授权状态流转。

- process_wait_effective: 每 5 分钟扫描 wait_effect → active
- process_expired: 每 5 分钟扫描 active → expired

beat 配置在 celery_app 中注册。
"""

from __future__ import annotations

import asyncio
import logging

from internal.domain.auth.grant_service import GrantService
from internal.domain.auth.service import AuthService
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.apps.auth_repository import AuthRepository

logger = logging.getLogger(__name__)


def _run_process(kind: str) -> int:
    """同步执行状态流转（DB 是同步 session，用 asyncio.run 包异步领域服务）。"""
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


@celery_app.task(name="auth.process_wait_effective")
def process_wait_effective_task() -> int:
    """定时：到点激活 wait_effect 授权。"""
    count = _run_process("wait_effective")
    logger.info("wait_effective 任务完成，激活 %d 条", count)
    return count


@celery_app.task(name="auth.process_expired")
def process_expired_task() -> int:
    """定时：到期过期 active 授权。"""
    count = _run_process("expired")
    logger.info("expired 任务完成，过期 %d 条", count)
    return count
