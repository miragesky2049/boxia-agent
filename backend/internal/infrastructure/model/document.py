"""知识库文档与分块 ORM 模型：RAG 链路持久化层。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base, UuidPrimaryKey


class DocumentModel(Base):
    """documents 表：知识库文档元数据；原文内容不存本表，仅存 source_uri / content_hash。"""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_tenant_agent", "tenant_id", "agent_id"),)

    id: Mapped[UuidPrimaryKey]
    # NULL 表示产品级知识库；非空表示租户私有知识库
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    # 所属智能体；文档可被多个智能体通过 agent.config.retrieval.document_ids 引用，
    # 这里 agent_id 仅用于默认归属与权限收敛，不做唯一约束。
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 来源类型：text / markdown / pdf / docx
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    # 来源标识：内联文本留空，文件上传后存对象 key 或本地路径
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # dev 阶段直接保留原文，便于 re-ingest；生产应切换到对象存储，该字段置空
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 内容哈希：用于判断原文是否变化，决定是否需要重新切分与向量化
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # ingest 状态：pending / processing / ready / failed
    ingest_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    ingest_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 额外元信息：上传者、原始文件名、页码范围等
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentChunkModel(Base):
    """document_chunks 表：文档切分后的最小检索单元，带 embedding 向量。"""

    __tablename__ = "document_chunks"
    # HNSW 索引在迁移中按 vector_cosine_ops 创建；这里只声明常用过滤索引
    __table_args__ = (
        Index("ix_document_chunks_document", "document_id"),
        Index("ix_document_chunks_tenant", "tenant_id"),
    )

    id: Mapped[UuidPrimaryKey]
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # 冗余存 tenant_id，便于检索时按租户过滤，避免 JOIN
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 结构化元数据：heading_path（标题层级路径）、source（来源页/章节）等
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    # 向量维度由 settings.embedding_dimensions 决定；迁移中按实际维度建列
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
