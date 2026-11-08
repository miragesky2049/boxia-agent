"""内存向量库实现：开发/测试用，不依赖外部服务。

生产环境应替换为 Milvus 或 PGVector 实现。
"""

from __future__ import annotations

import math
from typing import Any

from internal.domain.retrieval.model import Chunk, DatasetConfig, RetrievalResult
from internal.domain.retrieval.vector_store import VectorStore


class InMemoryVectorStore(VectorStore):
    """进程内向量库：dict 存储，余弦相似度检索。"""

    def __init__(self) -> None:
        self._datasets: dict[str, DatasetConfig] = {}
        self._chunks: dict[str, dict[str, Chunk]] = {}

    async def create_dataset(self, config: DatasetConfig) -> None:
        self._datasets[config.dataset_id] = config
        self._chunks.setdefault(config.dataset_id, {})

    async def drop_dataset(self, dataset_id: str) -> None:
        self._datasets.pop(dataset_id, None)
        self._chunks.pop(dataset_id, None)

    async def upsert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            bucket = self._chunks.setdefault(chunk.dataset_id, {})
            bucket[chunk.chunk_id] = chunk

    async def delete(self, dataset_id: str, chunk_ids: list[str]) -> None:
        bucket = self._chunks.get(dataset_id, {})
        for cid in chunk_ids:
            bucket.pop(cid, None)

    async def delete_by_document(
        self,
        dataset_id: str,
        document_id: str,
        tenant_id: str = "",
    ) -> None:
        bucket = self._chunks.get(dataset_id, {})
        for cid, chunk in list(bucket.items()):
            if chunk.document_id == document_id or chunk.metadata.get("document_id") == document_id:
                bucket.pop(cid, None)

    async def search(
        self,
        dataset_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict[str, Any] | None = None,
        tenant_id: str = "",
    ) -> list[RetrievalResult]:
        bucket = self._chunks.get(dataset_id, {})
        scored: list[RetrievalResult] = []
        for chunk in bucket.values():
            if filter_expr and not _match_filter(chunk.metadata, filter_expr):
                continue
            if not chunk.vector:
                continue
            score = _cosine(query_vector, chunk.vector)
            scored.append(RetrievalResult(chunk=chunk, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def health_check(self) -> bool:
        return True


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _match_filter(metadata: dict[str, Any], filter_expr: dict[str, Any]) -> bool:
    return all(metadata.get(k) == v for k, v in filter_expr.items())
