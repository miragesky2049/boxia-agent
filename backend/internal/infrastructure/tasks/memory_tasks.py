"""Celery 异步任务：长期记忆抽取（M4 PRD F16.3，20261107）。

主会话 assistant 消息落库提交后由 ChatService 投递 extract_memories(run_id)；
worker 进程自建 UoW 与仓储装配（先例 ingest_tasks.py）。启动命令（dev.sh 已含）：
    celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag
失败契约：重试 1 次仍失败仅记 warning 放弃——抽取是旁路增强，绝不无限重投；
对话主流程与投递点解耦（delay() 失败在投递侧降级，见 chat_service）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from internal.application.apps.memory_service import MemoryExtractorService
from internal.application.apps.model_service import ModelService
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.agent_memory_repository import AgentMemoryRepository
from internal.infrastructure.repository.apps.conversation_repository import ConversationRepository
from internal.infrastructure.repository.apps.message_repository import MessageRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository

logger = logging.getLogger(__name__)


def _build_extractor(session: Any) -> MemoryExtractorService:
    """worker 侧装配：session-per-repo，默认模型取 settings.llm_model_id。"""
    return MemoryExtractorService(
        model_service=ModelService(ModelRepository(session)),
        run_repo=RunRepository(session),
        msg_repo=MessageRepository(session),
        conv_repo=ConversationRepository(session),
        memory_repo=AgentMemoryRepository(session),
        default_model_id=get_settings().llm_model_id,
    )


@celery_app.task(name="memory.extract_memories", bind=True, max_retries=1)
def extract_memories(self, run_id: str) -> dict | None:
    """对一轮已落库对话执行长期记忆抽取（幂等由 source_run_id 探测保证）。"""
    try:
        uow = SqlAlchemyUnitOfWork()
        try:
            result = asyncio.run(_build_extractor(uow.session).extract_for_run(UUID(run_id)))
            uow.commit()
            return result
        finally:
            uow.close()
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.warning("记忆抽取最终失败（重试已用尽）run_id=%s: %s", run_id, exc)
            return None
        logger.warning("记忆抽取失败，30s 后重试 run_id=%s: %s", run_id, exc)
        raise self.retry(exc=exc, countdown=30) from exc
