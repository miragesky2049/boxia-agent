"""知识库文档与分块 PostgreSQL 仓储。"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.entity.document import Document, DocumentChunk
from internal.infrastructure.model.document import DocumentChunkModel, DocumentModel


def compute_content_hash(text: str) -> str:
    """计算原文 SHA-256，用于判断内容是否变化。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PostgresDocumentRepository:
    """documents 表仓储：按当前作用域（产品级 / 租户级）读写。"""

    def __init__(self, session: Session, tenant_id: UUID | None = None) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def _visible(self, stmt):
        """读可见范围：产品级视角仅 tenant_id IS NULL；租户视角含自有 + 产品级。"""
        if self._tenant_id is None:
            return stmt.where(DocumentModel.tenant_id.is_(None))
        return stmt.where(
            or_(
                DocumentModel.tenant_id == self._tenant_id,
                DocumentModel.tenant_id.is_(None),
            )
        )

    def _owned(self, stmt):
        """写归属范围：只能维护当前作用域自有的文档。"""
        if self._tenant_id is None:
            return stmt.where(DocumentModel.tenant_id.is_(None))
        return stmt.where(DocumentModel.tenant_id == self._tenant_id)

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        agent_id: UUID | None = None,
        ingest_status: str | None = None,
    ) -> tuple[list[Document], int]:
        """分页查询；按创建时间倒序。"""
        base = self._visible(select(DocumentModel))
        count_stmt = self._visible(select(func.count(DocumentModel.id)))
        if keyword:
            like = f"%{keyword.strip()}%"
            base = base.where(DocumentModel.title.ilike(like))
            count_stmt = count_stmt.where(DocumentModel.title.ilike(like))
        if agent_id is not None:
            base = base.where(DocumentModel.agent_id == agent_id)
            count_stmt = count_stmt.where(DocumentModel.agent_id == agent_id)
        if ingest_status:
            base = base.where(DocumentModel.ingest_status == ingest_status)
            count_stmt = count_stmt.where(DocumentModel.ingest_status == ingest_status)

        total = self._session.scalar(count_stmt) or 0
        rows = self._session.scalars(
            base.order_by(DocumentModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_entity(row) for row in rows], total

    def get(self, document_id: UUID) -> Document | None:
        """按主键查询（限可见范围）。"""
        row = self._session.scalar(
            self._visible(select(DocumentModel)).where(DocumentModel.id == document_id)
        )
        return self._to_entity(row) if row else None

    def create(self, values: dict[str, Any]) -> Document:
        """创建文档元数据。"""
        row = DocumentModel(**values)
        self._session.add(row)
        self._session.flush()
        return self._to_entity(row)

    def update(self, document_id: UUID, values: dict[str, Any]) -> Document | None:
        """更新文档元数据；只允许维护当前作用域自有的文档。"""
        row = self._session.scalar(
            self._owned(select(DocumentModel)).where(DocumentModel.id == document_id)
        )
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        return self._to_entity(row)

    def delete(self, document_id: UUID) -> bool:
        """删除文档及其分块（CASCADE）。"""
        row = self._session.scalar(
            self._owned(select(DocumentModel)).where(DocumentModel.id == document_id)
        )
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    @staticmethod
    def _to_entity(row: DocumentModel) -> Document:
        """ORM → 领域实体。"""
        return Document(
            id=row.id,
            tenant_id=row.tenant_id,
            agent_id=row.agent_id,
            title=row.title,
            source_type=row.source_type,
            source_uri=row.source_uri,
            raw_content=row.raw_content,
            content_hash=row.content_hash,
            ingest_status=row.ingest_status,
            ingest_error=row.ingest_error,
            chunk_count=row.chunk_count,
            metadata=dict(row.metadata_ or {}),
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class PostgresDocumentChunkRepository:
    """document_chunks 仓储：写入与向量检索。"""

    def __init__(self, session: Session, tenant_id: UUID | None = None) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def replace_for_document(
        self,
        document_id: UUID,
        tenant_id: UUID | None,
        chunks: list[dict[str, Any]],
    ) -> int:
        """全量替换某文档的分块：先删旧块，再批量插入新块。返回插入条数。"""
        self._session.execute(
            DocumentChunkModel.__table__.delete().where(  # type: ignore[attr-defined]
                DocumentChunkModel.document_id == document_id
            )
        )
        rows = [
            DocumentChunkModel(
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_index=item["chunk_index"],
                content=item["content"],
                token_count=item.get("token_count") or 0,
                embedding=item.get("embedding"),
                metadata_=item.get("metadata") or {},
            )
            for item in chunks
        ]
        self._session.add_all(rows)
        self._session.flush()
        return len(rows)

    def search_similar(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        document_ids: list[UUID] | None = None,
    ) -> list[DocumentChunk]:
        """按余弦距离检索 top_k 分块；返回的实体附带 score（相似度，越大越相似）。"""
        # pgvector 余弦距离 <=>；相似度 = 1 - distance
        distance_column = DocumentChunkModel.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                DocumentChunkModel,
                (1 - distance_column).label("score"),
            )
            .where(DocumentChunkModel.embedding.is_not(None))
            .order_by(distance_column)
            .limit(top_k)
        )
        if self._tenant_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentChunkModel.tenant_id == self._tenant_id,
                    DocumentChunkModel.tenant_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(DocumentChunkModel.tenant_id.is_(None))
        if document_ids:
            stmt = stmt.where(DocumentChunkModel.document_id.in_(document_ids))

        rows = self._session.execute(stmt).all()
        result: list[DocumentChunk] = []
        for row, score in rows:
            result.append(
                DocumentChunk(
                    id=row.id,
                    document_id=row.document_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    token_count=row.token_count,
                    created_at=row.created_at,
                    tenant_id=row.tenant_id,
                    embedding=None,
                    metadata=dict(row.metadata_ or {}),
                    score=float(score or 0.0),
                )
            )
        return result
