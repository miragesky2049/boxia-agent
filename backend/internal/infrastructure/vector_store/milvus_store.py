"""Milvus 向量库实现。

依赖 pymilvus（Milvus 官方 Python SDK）。集合命名按租户隔离：`{tenant}_{dataset}`。
"""

from __future__ import annotations

import logging
from typing import Any

from internal.domain.retrieval.model import Chunk, DatasetConfig, RetrievalResult
from internal.domain.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MilvusVectorStore(VectorStore):
    """Milvus 实现。

    Args:
        uri: Milvus 服务地址（如 "http://localhost:19530"）
        token: 访问令牌（用户名:密码，本地开发可留空）
        default_tenant: 默认租户命名空间
    """

    def __init__(self, uri: str, token: str = "", default_tenant: str = "public"):
        self._uri = uri
        self._token = token
        self._default_tenant = default_tenant
        self._connected = False
        self._collections: dict[str, Any] = {}

    def _ensure_connected(self) -> Any:
        """延迟连接 Milvus，避免 import 时硬依赖 pymilvus。"""
        if self._connected:
            return self._collections
        from pymilvus import connections  # type: ignore[import-untyped]

        connections.connect(alias="default", uri=self._uri, token=self._token or None)
        self._connected = True
        return self._collections

    def _collection_name(self, dataset_id: str, tenant_id: str = "") -> str:
        tenant = tenant_id or self._default_tenant
        return f"{tenant}_{dataset_id}".replace("-", "_")

    async def create_dataset(self, config: DatasetConfig) -> None:
        from pymilvus import Collection, DataType, CollectionSchema, utility  # type: ignore[import-untyped]

        self._ensure_connected()
        name = self._collection_name(config.dataset_id, config.tenant_id)
        if utility.has_collection(name, using="default"):
            return

        fields = [
            {"name": "chunk_id", "dtype": DataType.VARCHAR, "is_primary": True, "max_length": 128},
            {"name": "content", "dtype": DataType.VARCHAR, "max_length": 65535},
            {"name": "document_id", "dtype": DataType.VARCHAR, "max_length": 128},
            {"name": "metadata", "dtype": DataType.JSON},
            {"name": "vector", "dtype": DataType.FLOAT_VECTOR, "dim": config.dimension},
        ]
        schema = CollectionSchema(fields, description=config.display_name)
        collection = Collection(name, schema=schema, using="default")

        index_params = {
            "metric_type": config.metric.upper(),
            "index_type": "AUTOINDEX",
            "params": {},
        }
        collection.create_index(field_name="vector", index_params=index_params)
        self._collections[name] = collection
        logger.info("Milvus 集合已创建: %s dim=%d", name, config.dimension)

    async def drop_dataset(self, dataset_id: str) -> None:
        from pymilvus import utility  # type: ignore[import-untyped]

        self._ensure_connected()
        name = self._collection_name(dataset_id)
        if utility.has_collection(name, using="default"):
            utility.drop_collection(name, using="default")
            self._collections.pop(name, None)

    async def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        self._ensure_connected()
        dataset_id = chunks[0].dataset_id
        name = self._collection_name(dataset_id, chunks[0].metadata.get("_tenant_id", ""))
        collection = self._collections.get(name) or await self._load_collection(name)

        rows = [
            [c.chunk_id for c in chunks],
            [c.content for c in chunks],
            [c.document_id for c in chunks],
            [c.metadata for c in chunks],
            [c.vector or [] for c in chunks],
        ]
        collection.upsert(rows)
        collection.flush()

    async def delete(self, dataset_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._ensure_connected()
        name = self._collection_name(dataset_id)
        collection = self._collections.get(name) or await self._load_collection(name)
        expr = f'chunk_id in {chunk_ids!r}'
        collection.delete(expr)

    async def search(
        self,
        dataset_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict[str, Any] | None = None,
        tenant_id: str = "",
    ) -> list[RetrievalResult]:
        self._ensure_connected()
        name = self._collection_name(dataset_id, tenant_id)
        collection = self._collections.get(name) or await self._load_collection(name)
        collection.load()

        expr = None
        if filter_expr:
            clauses = [f'metadata["{k}"] == "{v}"' for k, v in filter_expr.items()]
            expr = " and ".join(clauses)

        hits = collection.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id", "content", "document_id", "metadata"],
        )

        results: list[RetrievalResult] = []
        for hit in hits[0]:
            entity = hit.entity
            chunk = Chunk(
                chunk_id=str(entity.get("chunk_id")),
                content=str(entity.get("content")),
                dataset_id=dataset_id,
                document_id=str(entity.get("document_id", "")),
                metadata=dict(entity.get("metadata") or {}),
            )
            results.append(RetrievalResult(chunk=chunk, score=float(hit.score)))
        return results

    async def health_check(self) -> bool:
        try:
            self._ensure_connected()
            return True
        except Exception:
            logger.exception("Milvus 探活失败")
            return False

    async def _load_collection(self, name: str) -> Any:
        from pymilvus import Collection  # type: ignore[import-untyped]

        collection = Collection(name, using="default")
        self._collections[name] = collection
        return collection
