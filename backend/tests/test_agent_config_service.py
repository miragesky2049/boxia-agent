"""0074 PRD F2：智能体配置应用服务单测（application/apps/agent_config_service）。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from internal.application.apps.agent_config_service import AgentConfigService
from internal.application.errors import NotFoundError, ValidationError


def _literal(value: object) -> dict:
    return {"value": {"type": "literal", "content": value}}


def _pack(flow_type: str = "agent", inputs: dict | None = None) -> dict:
    return {
        "flow_type": flow_type,
        "version": 1,
        "graph": {
            "nodes": [{
                "id": "agent_1",
                "type": "100",
                "data": {"inputs": inputs if inputs is not None else {
                    "modleName": _literal("m1"),
                    "systemPrompt": _literal("你是助手"),
                }, "outputs": []},
            }],
            "edges": [],
        },
    }


class _FakeAppService:
    """只模拟 AgentConfigService 用到的两个端口方法；graph 就地可变，模拟持久化。"""

    def __init__(self, pack: dict | None) -> None:
        self._pack = pack
        self.saved: list[dict] = []

    def get_graph(self, application_id):
        return self._pack

    def save_graph(self, application_id, graph, *, changelog, actor_id=None, actor_username=""):
        self.saved.append({"graph": graph, "changelog": changelog, "actor_id": actor_id})
        return {"version": (self._pack or {}).get("version", 0) + 1}


def _service(pack: dict | None) -> tuple[AgentConfigService, _FakeAppService]:
    fake = _FakeAppService(pack)
    return AgentConfigService(fake), fake


class TestGetConfig:
    def test_reads_form_with_defaults(self) -> None:
        service, _ = _service(_pack())
        form = service.get_config(uuid4())
        assert form["systemPrompt"] == "你是助手"
        assert form["modleName"] == "m1"
        # 缺省补齐：配置面始终拿到完整表单
        assert form["maxToolRounds"] == 10
        assert form["datasets"] == []
        assert form["memory"]["shortTerm"]["enabled"] is True

    def test_missing_graph_raises_not_found(self) -> None:
        service, _ = _service(None)
        with pytest.raises(NotFoundError):
            service.get_config(uuid4())

    def test_non_agent_app_rejected(self) -> None:
        service, _ = _service(_pack(flow_type="chatflow"))
        with pytest.raises(ValidationError, match="不是智能体类型"):
            service.get_config(uuid4())

    def test_canvas_without_agent_node_rejected(self) -> None:
        pack = _pack()
        pack["graph"]["nodes"][0]["type"] = "3"
        service, _ = _service(pack)
        with pytest.raises(ValidationError, match="缺少 Agent 循环节点"):
            service.get_config(uuid4())


class TestSaveConfig:
    def test_saves_valid_form_and_reads_back(self) -> None:
        service, fake = _service(_pack())
        form = {
            "systemPrompt": "你是产品顾问",
            "modleName": "gpt-4o",
            "maxToolRounds": 8,
            "tools": [],
            "datasets": [{"datasetId": "d1", "mode": "always", "topK": 4}],
            "memory": {"shortTerm": {"windowTurns": 6}},
            "reasoningMode": "react",
            "openingRemarks": "你好",
            "suggestedQuestions": ["问题1"],
        }
        result = service.save_config(uuid4(), form, actor_id=uuid4(), actor_username="admin")

        assert result["systemPrompt"] == "你是产品顾问"
        assert result["datasets"][0]["datasetId"] == "d1"
        assert result["memory"]["shortTerm"]["windowTurns"] == 6
        # 走 save_graph 版本链路：一次保存、带 changelog、透传操作人
        assert len(fake.saved) == 1
        assert fake.saved[0]["changelog"] == "智能体配置更新"
        assert fake.saved[0]["actor_id"] is not None

    def test_invalid_form_rejected_without_save(self) -> None:
        service, fake = _service(_pack())
        with pytest.raises(ValidationError, match="智能体配置不合法"):
            service.save_config(uuid4(), {"systemPrompt": "", "modleName": ""})
        assert fake.saved == []

    def test_non_agent_app_rejected(self) -> None:
        service, fake = _service(_pack(flow_type="workflow"))
        with pytest.raises(ValidationError, match="不是智能体类型"):
            service.save_config(uuid4(), {"systemPrompt": "s", "modleName": "m"})
        assert fake.saved == []
