"""document_chunks 增加 metadata JSONB 列：存标题路径、来源等结构化信息。

Revision ID: 0023_document_chunks_metadata
Revises: 0022_rag_documents
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_document_chunks_metadata"
down_revision: str | None = "0022_rag_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 document_chunks 增加 metadata JSONB 列，默认空对象。"""
    op.add_column(
        "document_chunks",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    """回滚：删除 metadata 列。"""
    op.drop_column("document_chunks", "metadata")
