"""PGVector 向量库实现。

复用项目已有的 PostgreSQL 连接（SQLAlchemy sync engine），通过 pgvector 扩展。
每个 dataset 对应一张表：
    {dataset_id}  {
        chunk_id   varchar primary key,
        tenant_id  varchar not null,
        content    text,
        document_id varchar,
        metadata   jsonb,
        vector     vector(N)
    }

相似度度量默认 cosine（<=> 距离运算符）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from internal.domain.retrieval.model import Chunk, DatasetConfig, RetrievalResult
from internal.domain.retrieval.vector_store import VectorStore
from internal.infrastructure.model.database import get_session_factory

logger = logging.getLogger(__name__)


class PGVectorStore(VectorStore):
    """基于 PGVector 的向量库实现。

    不持有自己的连接池，直接复用项目 `get_session_factory()`。
    测试时可通过构造函数注入自定义 session_factory。
    """

    def __init__(self, session_factory: Any = None):
        self._session_factory = session_factory or get_session_factory()

    async def create_dataset(self, config: DatasetConfig) -> None:
        """幂等创建 pgvector 扩展 + 数据集表。"""
        table = self._table_name(config.dataset_id)
        dimension = config.dimension
        with self._session_factory() as session:
            session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            session.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    chunk_id VARCHAR(128) PRIMARY KEY,
                    tenant_id VARCHAR(64) NOT NULL,
                    content TEXT NOT NULL,
                    document_id VARCHAR(128) DEFAULT '',
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    vector vector({int(dimension)}) NOT NULL
                )
            """))
            # 索引：HNSW + cosine ops，适合中等规模
            session.execute(text(f"""
                CREATE INDEX IF NOT EXISTS {table}_vector_idx
                ON {table} USING hnsw (vector vector_cosine_ops)
            """))
            session.commit()
        logger.info("PGVector 表已就绪: %s dim=%d", table, dimension)

    async def drop_dataset(self, dataset_id: str) -> None:
        table = self._table_name(dataset_id)
        with self._session_factory() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            session.commit()

    async def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        table = self._table_name(chunks[0].dataset_id)
        rows = [
            {
                "chunk_id": c.chunk_id,
                "tenant_id": str(c.metadata.get("_tenant_id", "")),
                "content": c.content,
                "document_id": c.document_id,
                "metadata": c.metadata,
                "vector": list(c.vector or []),
            }
            for c in chunks
        ]
        with self._session_factory() as session:
            for row in rows:
                session.execute(
                    text(f"""
                        INSERT INTO {table}
                            (chunk_id, tenant_id, content, document_id, metadata, vector)
                        VALUES
                            (:chunk_id, :tenant_id, :content, :document_id, CAST(:metadata AS jsonb), :vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            content = EXCLUDED.content,
                            document_id = EXCLUDED.document_id,
                            metadata = EXCLUDED.metadata,
                            vector = EXCLUDED.vector
                    """),
                    {
                        **row,
                        "metadata": __import__("json").dumps(row["metadata"], ensure_ascii=False),
                        "vector": str(row["vector"]),
                    },
                )
            session.commit()

    async def delete(self, dataset_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        table = self._table_name(dataset_id)
        with self._session_factory() as session:
            session.execute(
                text(f"DELETE FROM {table} WHERE chunk_id = ANY(:ids)"),
                {"ids": chunk_ids},
            )
            session.commit()

    async def delete_by_document(
        self,
        dataset_id: str,
        document_id: str,
        tenant_id: str = "",
    ) -> None:
        if not document_id:
            return
        table = self._table_name(dataset_id)
        where = "document_id = :document_id"
        params: dict[str, Any] = {"document_id": document_id}
        if tenant_id:
            where += " AND tenant_id = :tenant_id"
            params["tenant_id"] = str(tenant_id)
        with self._session_factory() as session:
            session.execute(text(f"DELETE FROM {table} WHERE {where}"), params)
            session.commit()

    async def search(
        self,
        dataset_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict[str, Any] | None = None,
        tenant_id: str = "",
    ) -> list[RetrievalResult]:
        table = self._table_name(dataset_id)
        where_clauses: list[str] = []
        params: dict[str, Any] = {"qvec": str(query_vector), "k": int(top_k)}

        if tenant_id:
            where_clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        for key, value in (filter_expr or {}).items():
            placeholder = f"meta_{key}"
            where_clauses.append(f"metadata->>'{key}' = :{placeholder}")
            params[placeholder] = str(value)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with self._session_factory() as session:
            rows = session.execute(
                text(f"""
                    SELECT chunk_id, content, document_id, metadata,
                           1 - (vector <=> :qvec::vector) AS score
                    FROM {table}
                    {where_sql}
                    ORDER BY vector <=> :qvec::vector
                    LIMIT :k
                """),
                params,
            ).mappings().all()

        results: list[RetrievalResult] = []
        for row in rows:
            chunk = Chunk(
                chunk_id=row["chunk_id"],
                content=row["content"],
                dataset_id=dataset_id,
                document_id=row.get("document_id") or "",
                metadata=dict(row.get("metadata") or {}),
            )
            results.append(RetrievalResult(chunk=chunk, score=float(row["score"])))
        return results

    async def health_check(self) -> bool:
        try:
            with self._session_factory() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("PGVector 探活失败")
            return False

    @staticmethod
    def _table_name(dataset_id: str) -> str:
        """表名规范化：去掉非法字符，加前缀避免与业务表冲突。"""
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in dataset_id)
        return f"vec_{safe.lower()}"
