"""T13：发布动作（draft → live 快照）单测。

验证：
1. publish_graph 把 application.published_graph_version 指向 latest 版本
2. get_runtime_graph 在未发布时回退 latest（向后兼容）
3. get_runtime_graph 在发布后取 published 版本，而不是未发布的新 draft
4. 无 graph 时 publish 抛 NotFoundError
5. 发布闸门：画布引用不在启用模型目录中的 modleName 时拦截发布
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from internal.application.apps.application_service import ApplicationService
from internal.application.errors import NotFoundError, ValidationError


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
        # DDD 四期：save/publish 审计走 uow.audit_logs
        self.audit_logs = MagicMock()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class FakeModelRepo:
    """最小模型目录 fake：只为发布闸门提供启用中的 model_id 集合。"""

    def __init__(self, model_ids: list[str]) -> None:
        self._model_ids = model_ids

    def list_catalog(self) -> list[dict]:
        return [{"model_id": m, "display_name": m, "capabilities": {}, "provider_name": "deepseek"}
                for m in self._model_ids]


def _make_service(model_repo: object | None = None) -> tuple[ApplicationService, UUID, FakeAppRepo]:
    uow = FakeUow()
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    cache.delete = AsyncMock(return_value=None)
    cache.publish = AsyncMock(return_value=None)
    repo = FakeAppRepo()
    # DDD 四期：fake 仓储改由构造参数注入
    service = ApplicationService(
        uow, repo, cache=cache, object_storage=None, default_llm_model_id="test-model",
        model_repo=model_repo,
    )
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


def _save_agent_draft(service: ApplicationService, app_id: UUID, model_id: str) -> int:
    """start→agent 两节点画布（coze 数字形态），agent 节点绑定指定模型。"""
    graph = {"nodes": [
        {"id": "start_1", "type": "1", "data": {"inputs": {"inputParameters": []}, "outputs": [],
         "nodeMeta": {"title": "开始"}}},
        {"id": "agent_1", "type": "100", "data": {"inputs": {
            "modleName": {"value": {"type": "literal", "content": model_id}},
            "systemPrompt": {"value": {"type": "literal", "content": "S"}},
        }, "outputs": [], "nodeMeta": {"title": "Agent"}}},
    ], "edges": []}
    return service.save_graph(app_id, graph, changelog="agent draft")["version"]


def test_publish_blocks_unknown_model_reference():
    """画布引用目录中不存在的模型（如测试占位模型）时发布被拦截。"""
    service, app_id, repo = _make_service(model_repo=FakeModelRepo(["deepseek-v4-flash"]))
    _save_agent_draft(service, app_id, "vision-test-model")

    with pytest.raises(ValidationError, match="vision-test-model"):
        service.publish_graph(app_id)
    assert repo.applications[str(app_id)]["published_graph_version"] is None


def test_publish_allows_catalog_model_and_empty_reference():
    """目录内模型可发布；未配置模型的画布不受闸门影响。"""
    service, app_id, repo = _make_service(model_repo=FakeModelRepo(["deepseek-v4-flash"]))
    _save_agent_draft(service, app_id, "deepseek-v4-flash")
    assert service.publish_graph(app_id)["published_version"] == 1

    # 无模型引用的普通画布（既有 _save_draft 形态）同样放行
    service2, app_id2, _ = _make_service(model_repo=FakeModelRepo([]))
    _save_draft(service2, app_id2, "v1")
    assert service2.publish_graph(app_id2)["published_version"] == 1


def test_publish_without_model_repo_skips_gate():
    """轻量 fake 装配（未注入 model_repo）时跳过模型检查，不误拦截。"""
    service, app_id, repo = _make_service()
    _save_agent_draft(service, app_id, "vision-test-model")
    assert service.publish_graph(app_id)["published_version"] == 1
