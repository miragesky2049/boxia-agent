"""Celery 异步任务：线上采样 judge 判定（M4-d PRD F19.3，20261108）。

主会话 assistant 消息落库提交后由 ChatService 按 rate 抽中投递 judge_sampling(run_id)
（与记忆抽取同任务通道：rag 队列、worker 自建 UoW）；判定与落库在
JudgeSamplingService，幂等由 has_runtime_sample 探测保证。
失败契约：重试 1 次仍失败仅记 warning 放弃——采样是观测旁路，绝不无限重投。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from internal.application.apps.judge_sampling_service import JudgeSamplingService
from internal.application.apps.model_service import ModelService
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.message_repository import MessageRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.usage_repository import UsageRepository

logger = logging.getLogger(__name__)


def _build_service(session: Any) -> JudgeSamplingService:
    """worker 侧装配：session-per-repo，默认模型取 settings.llm_model_id（抽取先例）。"""
    return JudgeSamplingService(
        run_repo=RunRepository(session),
        msg_repo=MessageRepository(session),
        eval_repo=EvalRepository(session),
        usage_repo=UsageRepository(session),
        model_service=ModelService(ModelRepository(session)),
        default_model_id=get_settings().llm_model_id,
    )


@celery_app.task(name="eval.judge_sampling", bind=True, max_retries=1)
def judge_sampling(self, run_id: str) -> dict | None:
    """对一轮已落库对话执行采样判定（仅按 run 成功终态投递，判定含全部跳过口径）。"""
    try:
        uow = SqlAlchemyUnitOfWork()
        try:
            # worker 无请求态：裸 SQL 仓储按 run 行 tenant_id 硬条件访问，无需角色过滤
            uow.apply_scope((), apply_role_filter=False)
            result = asyncio.run(_build_service(uow.session).sample_for_run(UUID(run_id)))
            uow.commit()
            return result
        finally:
            uow.close()
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.warning("judge 采样最终失败（重试已用尽）run_id=%s: %s", run_id, exc)
            return None
        logger.warning("judge 采样失败，30s 后重试 run_id=%s: %s", run_id, exc)
        raise self.retry(exc=exc, countdown=30) from exc
