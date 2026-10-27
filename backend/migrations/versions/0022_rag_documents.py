"""RAG 知识库：documents / document_chunks 表 + pgvector 扩展。

Revision ID: 0022_rag_documents
Revises: 0021_drop_umug_granted_by_fk
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0022_rag_documents"
down_revision: str | None = "0021_drop_umug_granted_by_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 与 settings.embedding_dimensions 对齐；变更维度时需重建向量列与索引
EMBEDDING_DIM = 1024


def upgrade() -> None:
    """启用 pgvector 扩展并创建 documents / document_chunks 表。"""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("source_uri", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("raw_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("ingest_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("ingest_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_tenant_agent", "documents", ["tenant_id", "agent_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_tenant", "document_chunks", ["tenant_id"])
    # HNSW 余弦距离索引：检索时 ORDER BY embedding <=> query_vec LIMIT k 走该索引
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_cosine "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """回滚：删除表与 vector 扩展。"""
    op.drop_index("ix_document_chunks_embedding_cosine", table_name="document_chunks")
    op.drop_index("ix_document_chunks_tenant", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_tenant_agent", table_name="documents")
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
