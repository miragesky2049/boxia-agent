"""Celery 异步任务：文档 ingest（切分 → embedding → 写入 document_chunks）。

worker 进程独立于 HTTP 服务运行，任务内部自建 UoW / RequestContext，
避免复用请求级依赖。启动命令：
    celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from internal.application.ingestion_service import IngestionService
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)


def _build_context(tenant_id: UUID | None) -> RequestContext:
    """worker 进程内构造 RequestContext：无 HTTP 请求，host 用占位值。"""
    if tenant_id is None:
        return RequestContext(
            scope="platform",
            tenant=None,
            host="celery-worker",
            resolution="default",
        )
    # 租户级：构造一个最小 Tenant 实体，只用于 can_manage 校验
    fake_tenant = Tenant(
        id=tenant_id,
        code="",
        name="",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return RequestContext(
        scope="tenant",
        tenant=fake_tenant,
        host="celery-worker",
        resolution="default",
    )


async def _run_ingest(document_id: UUID, tenant_id: UUID | None) -> int:
    """worker 进程内执行 ingest 全流程。"""
    settings = get_settings()
    uow = SqlAlchemyUnitOfWork(tenant_id=tenant_id)
    try:
        context = _build_context(tenant_id)
        document = uow.documents.get(document_id)
        if document is None:
            logger.warning("ingest task skipped: document not found id=%s", document_id)
            return 0

        service = IngestionService(uow, context)
        chunk_count = await service.ingest(
            document_id=document_id,
            raw_text=document.raw_content,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            source_type=document.source_type,
        )
        logger.info("ingest task done id=%s chunks=%d", document_id, chunk_count)
        return chunk_count
    finally:
        uow.close()


@celery_app.task(
    name="rag.ingest_document",
    bind=True,
    max_retries=2,
    retry_backoff=5,
    acks_late=True,
)
def ingest_document_task(self, document_id: str, tenant_id: str | None) -> int:
    """Celery 入口：把文档 ingest 丢到 worker 进程异步执行。

    Args:
        document_id: 文档 UUID 字符串
        tenant_id: 租户 UUID 字符串；None 表示产品级文档
    """
    doc_uuid = UUID(document_id)
    tenant_uuid = UUID(tenant_id) if tenant_id else None
    try:
        return asyncio.run(_run_ingest(doc_uuid, tenant_uuid))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest task failed id=%s err=%s", document_id, exc, exc_info=True)
        # 重试：embedding API 临时故障等瞬时错误
        raise self.retry(exc=exc) from exc
