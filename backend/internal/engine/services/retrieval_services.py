"""T2：把 embedding client + vector_store 组装成画布节点可直接消费的 service。

Dataset 节点（type=6）与 DatasetWrite 节点（type=27）期望从 `ctx.services` 拿到：
- `embedding`: 实现 `async embed(texts) -> list[list[float]]` 的客户端
- `vector_store`: 实现 `VectorStore` ABC 的实例

本模块提供进程级单例：
- embedding client 无状态，按 settings 构造一次
- vector_store 按 settings.vector_store_provider 选择 memory/pgvector/milvus 实现

当 embedding_api_key 未配置时不注册 embedding，节点 handler 自动走 stub 分支，
保证开发态零依赖可跑。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from internal.domain.retrieval.vector_store import VectorStore
from internal.engine.embedding import EmbeddingClient, OpenAICompatEmbeddingClient

logger = logging.getLogger(__name__)


class _RetrievalBundle:
    """一组检索依赖：embedding 可能为 None（未配置 api_key 时）。"""

    def __init__(self, embedding: EmbeddingClient | None, vector_store: VectorStore) -> None:
        self.embedding = embedding
        self.vector_store = vector_store


_bundle: _RetrievalBundle | None = None
_bundle_lock = threading.Lock()


def build_embedding_client() -> EmbeddingClient | None:
    """按 settings 构造 embedding 客户端；未配置 api_key 时返回 None。"""
    from internal.infrastructure.config.settings import get_settings

    settings = get_settings()
    api_key = settings.embedding_api_key.get_secret_value()
    if not api_key:
        logger.info("EMBEDDING_API_KEY 未配置，Dataset 节点将走 stub 分支")
        return None
    return OpenAICompatEmbeddingClient(
        api_key=api_key,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


def build_vector_store() -> VectorStore:
    """按 settings.vector_store_provider 构造向量库实现。"""
    from internal.infrastructure.config.settings import get_settings
    from internal.infrastructure.vector_store.factory import build_vector_store as _build

    settings = get_settings()
    provider = settings.vector_store_provider
    return _build(
        provider,
        uri=settings.milvus_uri,
        token=settings.milvus_token,
    )


def get_retrieval_bundle() -> _RetrievalBundle:
    """进程级单例：首次调用时按 settings 组装，后续直接返回。"""
    global _bundle
    if _bundle is not None:
        return _bundle
    with _bundle_lock:
        if _bundle is None:
            embedding = build_embedding_client()
            vector_store = build_vector_store()
            _bundle = _RetrievalBundle(embedding, vector_store)
            logger.info(
                "retrieval bundle ready: embedding=%s vector_store=%s",
                "on" if embedding is not None else "off",
                type(vector_store).__name__,
            )
    return _bundle


def register_retrieval_services(services: Any) -> None:
    """把 embedding / vector_store 注册进 ServiceRegistry。

    embedding 为 None 时跳过注册（Dataset 节点 handler 检测到无 embedding 自动走 stub）。
    """
    bundle = get_retrieval_bundle()
    services.register("vector_store", bundle.vector_store)
    if bundle.embedding is not None:
        services.register("embedding", bundle.embedding)
