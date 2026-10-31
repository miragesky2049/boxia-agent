"""知识库文档 CRUD 用例。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.entity.common import Page
from internal.domain.entity.document import Document
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.domain.retrieval.extractors import DocumentExtractError, extract_text

logger = logging.getLogger(__name__)


class DocumentService:
    """知识库文档元数据 CRUD。原文内容由 ingestion 异步处理，这里只维护元数据。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext) -> None:
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None = None,
        ingest_status: str | None = None,
    ) -> Page[Document]:
        """分页查询文档元数据。"""
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        items, total = self._uow.documents.list_page(
            page, page_size, keyword, ingest_status
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get(self, document_id: UUID) -> Document:
        """查询文档详情。"""
        item = self._uow.documents.get(document_id)
        if item is None:
            raise NotFoundError("文档不存在或当前作用域不可见")
        return item

    def create(
        self,
        *,
        title: str,
        source_type: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """创建文档元数据，并立刻触发切分 + 向量化（同步链路，便于 dev 联调）。"""
        if not title.strip():
            raise ValidationError("文档标题不能为空")

        try:
            text = extract_text(source_type, content)
        except DocumentExtractError as exc:
            raise ValidationError(str(exc)) from exc

        from internal.infrastructure.repository.postgres_document_repository import (
            compute_content_hash,
        )

        values = {
            "title": title.strip(),
            "source_type": source_type,
            "source_uri": "",
            "raw_content": text,
            "content_hash": compute_content_hash(text),
            "ingest_status": "pending",
            "ingest_error": "",
            "chunk_count": 0,
            "metadata": metadata or {},
            "is_enabled": True,
            "tenant_id": self._context.tenant_id,
        }
        document = self._uow.documents.create(values)
        self._uow.commit()
        logger.info("document created id=%s title=%s", document.id, document.title)
        return document

    def update(self, document_id: UUID, values: dict[str, Any]) -> Document:
        """更新文档元数据（标题、启用状态）。"""
        existing = self.get(document_id)
        if not self._context.can_manage(existing.tenant_id):
            raise ForbiddenError("无权维护该文档")
        updated = self._uow.documents.update(document_id, values)
        if updated is None:
            raise NotFoundError("文档不存在")
        self._uow.commit()
        return updated

    def delete(self, document_id: UUID) -> None:
        """删除文档及其分块（CASCADE）。"""
        existing = self.get(document_id)
        if not self._context.can_manage(existing.tenant_id):
            raise ForbiddenError("无权删除该文档")
        if not self._uow.documents.delete(document_id):
            raise NotFoundError("文档不存在")
        self._uow.commit()
