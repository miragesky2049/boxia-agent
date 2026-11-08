"""VectorStore 工厂与 InMemory 契约测试。"""

from __future__ import annotations

import asyncio

from internal.domain.retrieval.model import Chunk, DatasetConfig
from internal.infrastructure.vector_store import (
    InMemoryVectorStore,
    build_vector_store,
)


def test_factory_default_returns_inmemory():
    store = build_vector_store("memory")
    assert isinstance(store, InMemoryVectorStore)

    store = build_vector_store("unknown_provider")
    assert isinstance(store, InMemoryVectorStore)


def test_factory_pgvector_returns_pgvector_store():
    """pgvector provider 直接构造时不连接数据库，能返回实例即可。"""
    from internal.infrastructure.vector_store.pgvector_store import PGVectorStore

    store = build_vector_store("pgvector", session_factory=object())
    assert isinstance(store, PGVectorStore)


def test_inmemory_crud_roundtrip():
    """InMemory 实现的完整 CRUD：create → upsert → search → delete。"""
    store = InMemoryVectorStore()
    cfg = DatasetConfig(dataset_id="demo", display_name="demo", dimension=3)
    asyncio.run(store.create_dataset(cfg))

    chunks = [
        Chunk(
            chunk_id="c1",
            content="boxia 平台",
            dataset_id="demo",
            metadata={"tag": "intro"},
            vector=[1.0, 0.0, 0.0],
        ),
        Chunk(
            chunk_id="c2",
            content="向量数据库",
            dataset_id="demo",
            metadata={"tag": "tech"},
            vector=[0.0, 1.0, 0.0],
        ),
        Chunk(
            chunk_id="c3",
            content="boxia 是 SaaS",
            dataset_id="demo",
            metadata={"tag": "intro"},
            vector=[0.9, 0.1, 0.0],
        ),
    ]
    asyncio.run(store.upsert(chunks))

    # 检索 query=[1.0, 0, 0]，应该 c1 / c3 排前
    results = asyncio.run(store.search("demo", [1.0, 0.0, 0.0], top_k=2))
    assert [r.chunk.chunk_id for r in results] == ["c1", "c3"]

    # 元数据过滤
    results = asyncio.run(
        store.search(
            "demo",
            [1.0, 0.0, 0.0],
            top_k=5,
            filter_expr={"tag": "tech"},
        )
    )
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c2"

    # 删除 c1
    asyncio.run(store.delete("demo", ["c1"]))
    results = asyncio.run(store.search("demo", [1.0, 0.0, 0.0], top_k=5))
    assert all(r.chunk.chunk_id != "c1" for r in results)

    # 删库
    asyncio.run(store.drop_dataset("demo"))
    results = asyncio.run(store.search("demo", [1.0, 0.0, 0.0], top_k=5))
    assert results == []
