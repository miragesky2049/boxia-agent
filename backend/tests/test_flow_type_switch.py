"""流程类型切换的后端兼容校验。"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.application.apps.application_service import ApplicationService
from internal.application.errors import ValidationError


class _FakeRepo:
    def __init__(self, flow_type: str, graph: dict | None) -> None:
        self.app = {"id": str(uuid4()), "name": "demo", "flow_type": flow_type}
        self.graph = graph
        self.updated: dict = {}

    def get_application(self, application_id):
        return self.app

    def get_latest_graph_version(self, application_id):
        if self.graph is None:
            return None
        return {"version": 1, "graph": self.graph}

    def update_application(self, application_id, **kwargs):
        self.updated = kwargs
        if kwargs.get("flow_type"):
            self.app["flow_type"] = kwargs["flow_type"]


def _service(flow_type: str, graph: dict | None) -> tuple[ApplicationService, _FakeRepo]:
    uow = MagicMock()
    service = ApplicationService(uow, cache=MagicMock(), object_storage=None)
    repo = _FakeRepo(flow_type, graph)
    service._repo = repo
    return service, repo


def _graph(*type_codes: str) -> dict:
    return {
        "nodes": [
            {"id": f"n{i}", "type": code, "data": {"title": f"节点{i}"}}
            for i, code in enumerate(type_codes)
        ],
        "edges": [],
    }


def test_chatflow_to_workflow_allowed_when_output_node_exists():
    # 两种形态共用节点库，输出节点不再阻塞切换；运行期语义由执行入口校验
    service, repo = _service("chatflow", _graph("1", "13", "2"))
    service.update_application(uuid4(), flow_type="workflow")
    assert repo.updated["flow_type"] == "workflow"


def test_chatflow_to_workflow_allowed_for_plain_graph():
    service, repo = _service("chatflow", _graph("1", "3", "2"))
    app_id = uuid4()
    service.update_application(app_id, flow_type="workflow")
    assert repo.updated["flow_type"] == "workflow"


def test_workflow_to_chatflow_requires_start_and_end():
    service, _ = _service("workflow", _graph("1", "3"))
    with pytest.raises(ValidationError) as exc:
        service.update_application(uuid4(), flow_type="chatflow")
    assert "结束" in str(exc.value)


def test_workflow_to_chatflow_allowed_with_start_and_end():
    service, repo = _service("workflow", _graph("1", "3", "2"))
    service.update_application(uuid4(), flow_type="chatflow")
    assert repo.updated["flow_type"] == "chatflow"


def test_same_flow_type_skips_switch_validation():
    # 图里没有开始节点，但类型未变化时不触发切换校验
    service, repo = _service("workflow", _graph("3"))
    service.update_application(uuid4(), flow_type="workflow")
    assert repo.updated["flow_type"] == "workflow"
