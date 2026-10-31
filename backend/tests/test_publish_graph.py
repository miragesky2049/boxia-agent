"""T13：发布动作（draft → live 快照）单测。

验证：
1. publish_graph 把 application.published_graph_version 指向 latest 版本
2. get_runtime_graph 在未发布时回退 latest（向后兼容）
3. get_runtime_graph 在发布后取 published 版本，而不是未发布的新 draft
4. 无 graph 时 publish 抛 NotFoundError
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from internal.application.apps.application_service import ApplicationService
from internal.application.errors import NotFoundError


class FakeAppRepo:
    def __init__(self) -> None:
        self.applications: dict[str, dict] = {}
        self.versions: dict[tuple[str, int], dict] = {}
        self.latest: dict[str, int] = {}
        self.tenant_instances: dict[tuple, dict] = {}
        self.tenant_config: dict[tuple, dict] = {}
        self.published_set: list[int] = []

    def get_application(self, application_id):
        return self.applications.get(str(application_id))

    def get_latest_graph_version(self, application_id):
        app_id = str(application_id)
        v = self.latest.get(app_id)
        if v is None:
            return None
        return self.versions[(app_id, v)]

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
        }
        self.latest[app_id] = version

    def update_graph(self, application_id, graph, runtime_mode="dag"):
        pass

    def set_published_graph_version(self, application_id, version):
        self.published_set.append(version)
        self.applications[str(application_id)]["published_graph_version"] = version

    def get_instance(self, tenant_id, application_id):
        return self.tenant_instances.get((str(tenant_id), str(application_id)))

    def list_tenant_config(self, tenant_id, application_id):
        return self.tenant_config.get((str(tenant_id), str(application_id)), {})


class FakeUow:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _make_service() -> tuple[ApplicationService, UUID, FakeAppRepo]:
    uow = FakeUow()
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    cache.delete = AsyncMock(return_value=None)
    cache.publish = AsyncMock(return_value=None)
    service = ApplicationService(uow, cache=cache, object_storage=None)
    repo = FakeAppRepo()
    service._repo = repo  # type: ignore[assignment]
    app_id = uuid4()
    repo.applications[str(app_id)] = {
        "id": str(app_id),
        "name": "test",
        "owner_type": "platform",
        "published_graph_version": None,
    }
    return service, app_id, repo


def _save_draft(service: ApplicationService, app_id: UUID, version_tag: str) -> int:
    graph = {"nodes": [{"id": "n1", "type": "1", "data": {"tag": version_tag}}], "edges": []}
    result = service.save_graph(app_id, graph, changelog=f"save {version_tag}")
    return result["version"]


def test_publish_snapshots_latest_version():
    service, app_id, repo = _make_service()
    _save_draft(service, app_id, "v1")
    _save_draft(service, app_id, "v2")  # latest = 2

    result = service.publish_graph(app_id)
    assert result["published_version"] == 2
    assert repo.applications[str(app_id)]["published_graph_version"] == 2
    assert repo.published_set == [2]


def test_get_runtime_graph_before_publish_falls_back_to_latest():
    service, app_id, repo = _make_service()
    _save_draft(service, app_id, "v1")

    graph = asyncio.run(service.get_runtime_graph(app_id))
    assert graph["nodes"][0]["data"]["tag"] == "v1"


def test_get_runtime_graph_after_publish_uses_published_even_when_new_draft_saved():
    service, app_id, repo = _make_service()
    _save_draft(service, app_id, "v1")  # latest=1
    service.publish_graph(app_id)  # published=1

    _save_draft(service, app_id, "v2")  # latest=2，但 published 仍是 1

    graph = asyncio.run(service.get_runtime_graph(app_id))
    assert graph["nodes"][0]["data"]["tag"] == "v1"
    # latest 仍能从 repo 拿到（admin 侧读）
    assert repo.get_latest_graph_version(app_id)["version"] == 2


def test_publish_without_graph_raises():
    service, app_id, repo = _make_service()
    with pytest.raises(NotFoundError):
        service.publish_graph(app_id)
