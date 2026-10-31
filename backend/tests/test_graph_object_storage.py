"""A12：大 graph 对象存储单测。

验证：
1. 小 graph (<1MB) 直接内联写 DB
2. 大 graph (>1MB) 写入对象存储，DB 只存 `__graph_ref__` URI
3. 读取时自动从对象存储拉取真实 graph
4. 对象存储未配置时大 graph 降级为内联
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.application.apps.application_service import (
    ApplicationService,
    GRAPH_INLINE_SIZE_THRESHOLD,
)
from internal.domain.storage.object_storage import ObjectStorage
from internal.infrastructure.storage.fake_storage import InMemoryObjectStorage


class FakeApplicationRepository:
    """内存版 ApplicationRepository，只实现 save_graph/get_graph_version 用到的方法。"""

    def __init__(self) -> None:
        self.applications: dict = {}
        self.versions: dict[tuple, dict] = {}  # (app_id, version) -> record
        self.latest_version: dict = {}

    def get_application(self, application_id):
        return self.applications.get(str(application_id))

    def get_latest_graph_version(self, application_id):
        v = self.latest_version.get(str(application_id))
        if v is None:
            return None
        return self.versions[(str(application_id), v)]

    def get_graph_version(self, application_id, version):
        return self.versions.get((str(application_id), version))

    def insert_graph_version(self, application_id, version, graph, runtime_mode, changelog="", created_by=None):
        app_id = str(application_id)
        self.versions[(app_id, version)] = {
            "id": uuid4(),
            "application_id": app_id,
            "version": version,
            "graph": graph,
            "runtime_mode": runtime_mode,
            "changelog": changelog,
            "created_by": created_by,
        }
        self.latest_version[app_id] = version
        return self.versions[(app_id, version)]["id"]

    def update_graph(self, application_id, graph, runtime_mode="dag"):
        pass

    def list_graph_versions(self, application_id, limit=50):
        return []

    def get_instance(self, tenant_id, application_id):
        return None

    def list_tenant_config(self, tenant_id, application_id):
        return {}


class FakeUow:
    def __init__(self) -> None:
        self.session = MagicMock()

    def commit(self) -> None:
        pass


def _make_service(storage: ObjectStorage | None = None) -> ApplicationService:
    uow = FakeUow()
    service = ApplicationService(uow, cache=MagicMock(), object_storage=storage)
    # 替换 repo 为 fake
    service._repo = FakeApplicationRepository()
    # 预置一个应用
    app_id = uuid4()
    service._repo.applications[str(app_id)] = {"id": str(app_id), "name": "test", "owner_type": "platform"}
    return service, app_id


def test_small_graph_goes_inline():
    """小 graph 直接内联写 DB，不触发对象存储。"""
    storage = InMemoryObjectStorage()
    service, app_id = _make_service(storage)

    graph = {"nodes": [{"id": "n1", "type": "1"}], "edges": []}
    result = service.save_graph(app_id, graph, changelog="v1")

    assert result["version"] == 1
    # DB 里存的是完整 graph，不是 URI 引用
    record = service._repo.versions[(str(app_id), 1)]
    assert "__graph_ref__" not in record["graph"]
    assert record["graph"]["nodes"] == graph["nodes"]
    # 对象存储里没有东西
    assert len(storage._store) == 0


def _make_large_graph() -> dict:
    """构造一个 >1MB 的合法 graph（start -> llm -> end）。"""
    big_prompt = "x" * (GRAPH_INLINE_SIZE_THRESHOLD + 200)
    return {
        "nodes": [
            {"id": "start_1", "type": "1", "data": {"inputs": {}, "outputs": []}},
            {
                "id": "llm_1",
                "type": "3",
                "data": {
                    "inputs": {
                        "modleName": {"value": {"type": "literal", "content": "gpt-4o"}},
                        "prompt": {"value": {"type": "literal", "content": big_prompt}},
                    },
                    "outputs": [],
                },
            },
            {"id": "end_1", "type": "2", "data": {"inputs": {"content": "ok"}, "outputs": []}},
        ],
        "edges": [
            {"sourceNodeID": "start_1", "targetNodeID": "llm_1", "sourcePortID": ""},
            {"sourceNodeID": "llm_1", "targetNodeID": "end_1", "sourcePortID": ""},
        ],
    }


def test_large_graph_uploads_to_object_storage():
    """大 graph (>1MB) 写入对象存储，DB 只存 __graph_ref__。"""
    storage = InMemoryObjectStorage()
    service, app_id = _make_service(storage)

    graph = _make_large_graph()
    result = service.save_graph(app_id, graph, changelog="large")
    assert result["version"] == 1

    # DB 里应该是 URI 引用，不是完整 graph
    record = service._repo.versions[(str(app_id), 1)]
    assert "__graph_ref__" in record["graph"]
    uri = record["graph"]["__graph_ref__"]
    assert uri.startswith("memory://")

    # 对象存储里应该有真实 graph
    assert uri in storage._store
    stored_graph = json.loads(storage._store[uri])
    prompt_value = stored_graph["nodes"][1]["data"]["inputs"]["prompt"]["value"]["content"]
    assert prompt_value.startswith("x" * 10)


def test_read_large_graph_resolves_uri():
    """读取大 graph 时自动从对象存储拉取，返回完整 graph。"""
    storage = InMemoryObjectStorage()
    service, app_id = _make_service(storage)

    graph = _make_large_graph()
    service.save_graph(app_id, graph, changelog="large")

    # 重新读出来
    loaded = service.get_graph(app_id)
    assert loaded is not None
    loaded_graph = loaded["graph"]
    assert loaded_graph["nodes"][1]["id"] == "llm_1"
    prompt_value = loaded_graph["nodes"][1]["data"]["inputs"]["prompt"]["value"]["content"]
    assert prompt_value.startswith("x" * 10)


def test_large_graph_without_storage_degrades_inline():
    """对象存储未配置时，大 graph 降级为内联写 DB（不报错）。"""
    service, app_id = _make_service(storage=None)  # 无对象存储

    graph = _make_large_graph()
    result = service.save_graph(app_id, graph, changelog="large")
    assert result["version"] == 1

    # DB 里是完整 graph（内联）
    record = service._repo.versions[(str(app_id), 1)]
    assert "__graph_ref__" not in record["graph"]
    assert record["graph"]["nodes"][1]["id"] == "llm_1"
