"""Dataset / DatasetWrite 节点测试：验证 stub 路径与 InMemory 向量库闭环。"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.graph.node_base import NodeContext, NodeResult, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.dataset import DatasetNodeHandler
from internal.domain.graph.nodes.dataset_write import DatasetWriteNodeHandler
from internal.infrastructure.vector_store.in_memory_store import InMemoryVectorStore


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="dataset-test",
        application_id=uuid4(),
    )


class FakeEmbedding:
    """固定向量 embedding：按文本 hash 生成确定性向量，便于测试。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(hash(t) % 100) / 100.0, 0.5, 0.25] for t in texts]


def test_dataset_node_stub_when_no_services():
    """未注入 vector_store / embedding 时走 stub 分支。"""
    handler = DatasetNodeHandler()
    ctx = NodeContext(
        node_id="ds_1",
        node_type="6",
        inputs={"query": "你好"},
        config={"datasetId": "ds_1", "topK": 3},
        env=_make_env(),
        services=ServiceRegistry(),
    )
    result: NodeResult = asyncio.run(handler.run(ctx))
    assert "stub" in result.outputs
    assert result.outputs["chunks"] == []


def test_dataset_write_then_search_roundtrip():
    """用 InMemoryVectorStore 验证写入→检索闭环。"""
    store = InMemoryVectorStore()
    services = ServiceRegistry({"vector_store": store, "embedding": FakeEmbedding()})
    env = _make_env()

    write_handler = DatasetWriteNodeHandler()
    write_ctx = NodeContext(
        node_id="dw_1",
        node_type="27",
        inputs={"content": "boxia 是一个多租户 AI Agent 平台", "metadata": {"tag": "intro"}},
        config={"datasetId": "demo_ds"},
        env=env,
        services=services,
    )
    write_result = asyncio.run(write_handler.run(write_ctx))
    assert write_result.outputs["success"] is True

    search_handler = DatasetNodeHandler()
    search_ctx = NodeContext(
        node_id="ds_1",
        node_type="6",
        inputs={"query": "boxia 平台"},
        config={"datasetId": "demo_ds", "topK": 5},
        env=env,
        services=services,
    )
    search_result = asyncio.run(search_handler.run(search_ctx))
    assert search_result.outputs["count"] >= 1
    assert "boxia" in search_result.outputs["chunks"][0]["content"]
