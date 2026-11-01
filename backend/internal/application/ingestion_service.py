"""文档入库用例：切分 → 批量 embedding → 写入 document_chunks。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.domain.retrieval.embedding import EmbeddingClient
from internal.domain.retrieval.text_split import Chunk, split_markdown, split_text

logger = logging.getLogger(__name__)


class IngestionService:
    """文档 ingest：把原文切成 chunk 并向量化写入 document_chunks。

    生产环境由 Celery 异步任务触发（见 internal/infrastructure/tasks/ingest_tasks.py）；
    同步实现仍保留，便于脚本/测试直接调用。
    """

    def __init__(
        self,
        uow: UnitOfWork,
        context: RequestContext,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._uow = uow
        self._context = context
        self._embedding_client = embedding_client

    async def ingest(
        self,
        *,
        document_id: UUID,
        raw_text: str,
        chunk_size: int,
        chunk_overlap: int,
        source_type: str = "text",
    ) -> int:
        """执行 ingest 全流程：切分 → embedding → 替换 chunks。返回 chunk 数。"""
        document = self._uow.documents.get(document_id)
        if document is None:
            raise NotFoundError("文档不存在或当前作用域不可见")
        if not self._context.can_manage(document.tenant_id):
            raise ValidationError("无权对该文档执行 ingest")

        # 标记处理中，便于前端轮询
        self._uow.documents.update(
            document_id,
            {"ingest_status": "processing", "ingest_error": ""},
        )
        self._uow.commit()

        try:
            chunks = self._split(
                raw_text,
                source_type=source_type,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            if not chunks:
                raise ValidationError("文档内容为空，无法切分")

            client = self._resolve_client()
            embeddings = await client.embed([c.content for c in chunks])
            if len(embeddings) != len(chunks):
                raise ValidationError(
                    f"embedding 数量与 chunk 数不一致: {len(embeddings)} != {len(chunks)}"
                )

            rows: list[dict[str, Any]] = [
                {
                    "chunk_index": idx,
                    "content": chunk.content,
                    "token_count": len(chunk.content),
                    "embedding": embeddings[idx],
                    "metadata": {"heading_path": chunk.heading_path},
                }
                for idx, chunk in enumerate(chunks)
            ]
            inserted = self._uow.document_chunks.replace_for_document(
                document_id=document_id,
                tenant_id=document.tenant_id,
                chunks=rows,
            )
            self._uow.documents.update(
                document_id,
                {
                    "ingest_status": "ready",
                    "chunk_count": inserted,
                    "ingest_error": "",
                },
            )
            self._uow.commit()
            logger.info(
                "document ingested id=%s chunks=%d",
                document_id,
                inserted,
            )
            return inserted
        except Exception as exc:
            logger.warning("ingest failed id=%s err=%s", document_id, exc, exc_info=True)
            self._uow.documents.update(
                document_id,
                {"ingest_status": "failed", "ingest_error": str(exc)},
            )
            self._uow.commit()
            raise

    @staticmethod
    def _split(
        text: str,
        *,
        source_type: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[Chunk]:
        """按来源类型选择切分器：markdown 走标题感知切分，其他走段落滑窗。"""
        st = (source_type or "").lower()
        if st in {"markdown", "md"}:
            return split_markdown(
                text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
        plain_chunks = split_text(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return [Chunk(content=c, heading_path=[]) for c in plain_chunks]

    def _resolve_client(self) -> EmbeddingClient:
        """构造 embedding 客户端；测试可注入，生产从 settings 读取。"""
        if self._embedding_client is not None:
            return self._embedding_client
        from internal.domain.retrieval.embedding import OpenAICompatEmbeddingClient
        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        return OpenAICompatEmbeddingClient(
            api_key=settings.embedding_api_key.get_secret_value(),
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
