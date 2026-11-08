"""T2：retrieval service 组装函数单测。

覆盖：
1. embedding_api_key 为空时 build_embedding_client 返回 None。
2. build_vector_store 按 provider 返回对应实现。
3. register_retrieval_services 在 embedding=None 时只注册 vector_store。
4. register_retrieval_services 在 embedding 可用时同时注册两者。
5. 进程级单例 _bundle 只构造一次。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.retrieval.vector_store import VectorStore
from internal.infrastructure.retrieval import factory as retrieval_services
from internal.infrastructure.retrieval.factory import (
    build_embedding_client,
    build_vector_store,
    get_retrieval_bundle,
    register_retrieval_services,
)
from internal.infrastructure.vector_store.in_memory_store import InMemoryVectorStore


@pytest.fixture(autouse=True)
def _reset_bundle():
    """每个测试前重置进程级单例，避免跨用例污染。"""
    retrieval_services._bundle = None
    yield
    retrieval_services._bundle = None


class _FakeSettings:
    """最小 settings 替身：只覆盖 retrieval 相关字段。"""

    def __init__(
        self,
        *,
        embedding_api_key: str = "",
        embedding_base_url: str = "https://api.example.com/v1",
        embedding_model: str = "bge-test",
        embedding_timeout_seconds: float = 30.0,
        vector_store_provider: str = "memory",
        milvus_uri: str = "",
        milvus_token: str = "",
    ) -> None:
        from pydantic import SecretStr

        self.embedding_api_key = SecretStr(embedding_api_key)
        self.embedding_base_url = embedding_base_url
        self.embedding_model = embedding_model
        self.embedding_timeout_seconds = embedding_timeout_seconds
        self.vector_store_provider = vector_store_provider
        self.milvus_uri = milvus_uri
        self.milvus_token = milvus_token


def test_build_embedding_client_returns_none_when_no_api_key():
    settings = _FakeSettings(embedding_api_key="")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        assert build_embedding_client() is None


def test_build_embedding_client_returns_client_when_api_key_present():
    settings = _FakeSettings(embedding_api_key="sk-test")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        client = build_embedding_client()
        assert client is not None
        assert type(client).__name__ == "OpenAICompatEmbeddingClient"


def test_build_vector_store_memory_provider_returns_in_memory():
    settings = _FakeSettings(vector_store_provider="memory")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        store = build_vector_store()
        assert isinstance(store, InMemoryVectorStore)


def test_build_vector_store_unknown_provider_falls_back_to_in_memory():
    settings = _FakeSettings(vector_store_provider="redis")  # 未实现的 provider
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        store = build_vector_store()
        assert isinstance(store, InMemoryVectorStore)


def test_register_services_skips_embedding_when_not_configured():
    settings = _FakeSettings(embedding_api_key="", vector_store_provider="memory")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        services = ServiceRegistry()
        register_retrieval_services(services)

        assert services.has("vector_store")
        assert not services.has("embedding")


def test_register_services_registers_both_when_embedding_configured():
    settings = _FakeSettings(embedding_api_key="sk-test", vector_store_provider="memory")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        services = ServiceRegistry()
        register_retrieval_services(services)

        assert services.has("vector_store")
        assert services.has("embedding")


def test_bundle_is_process_singleton():
    settings = _FakeSettings(embedding_api_key="", vector_store_provider="memory")
    with patch(
        "internal.infrastructure.retrieval.factory.get_settings",
        return_value=settings,
    ):
        first = get_retrieval_bundle()
        second = get_retrieval_bundle()
        assert first is second
        assert first.embedding is None
        assert isinstance(first.vector_store, VectorStore)
