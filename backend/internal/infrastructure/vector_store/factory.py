"""VectorStore 工厂：按配置选择底层实现。

配置来源：settings.vector_store.provider = "milvus" | "pgvector" | "memory"。
"""

from __future__ import annotations

import logging

from internal.domain.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


def build_vector_store(provider: str = "memory", **kwargs) -> VectorStore:
    """按 provider 构造向量库实例。"""
    provider = provider.lower().strip()

    if provider == "milvus":
        from internal.infrastructure.vector_store.milvus_store import MilvusVectorStore
        return MilvusVectorStore(
            uri=kwargs.get("uri", ""),
            token=kwargs.get("token", ""),
            default_tenant=kwargs.get("default_tenant", "public"),
        )

    if provider == "pgvector":
        from internal.infrastructure.vector_store.pgvector_store import PGVectorStore
        return PGVectorStore(session_factory=kwargs.get("session_factory"))

    # 默认内存实现（开发/测试）
    if provider not in ("", "memory", "in_memory"):
        logger.warning("未知向量库 provider=%s，回退到 InMemory", provider)
    from internal.infrastructure.vector_store.in_memory_store import InMemoryVectorStore
    return InMemoryVectorStore()
