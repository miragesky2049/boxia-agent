"""0074 PRD F2：智能体配置表单 ⇄ 画布节点映射单测（domain/canvas/agent_config）。"""

from __future__ import annotations

from internal.domain.canvas.agent_config import (
    AGENT_NODE_TYPE_CODE,
    apply_form_to_node,
    find_agent_loop_node,
    node_config_to_form,
    validate_form,
)
from internal.domain.canvas.convert import find_agent_loop_config


def _literal(value: object) -> dict:
    return {"value": {"type": "literal", "content": value}}


def _agent_node(inputs: dict | None = None) -> dict:
    return {
        "id": "agent_1",
        "type": AGENT_NODE_TYPE_CODE,
        "data": {"inputs": inputs if inputs is not None else {}, "outputs": []},
    }


def _base_form() -> dict:
    return {
        "systemPrompt": "你是产品顾问",
        "modleName": "gpt-4o",
        "maxToolRounds": 8,
        "tools": [{"name": "get_weather", "description": "天气", "parameters": {}}],
        "datasets": [{"datasetId": "d1", "name": "产品库", "mode": "always", "topK": 4}],
        "memory": {"shortTerm": {"enabled": True, "windowTurns": 6, "tokenBudget": 1200}},
        "reasoningMode": "react",
        "openingRemarks": "你好，我可以帮你查产品资料。",
        "suggestedQuestions": ["退款政策", "蓝牙版本"],
    }


class TestFindNode:
    def test_find_agent_loop_node_by_type_code(self) -> None:
        graph = {"nodes": [{"id": "start_1", "type": "1"}, _agent_node()]}
        assert find_agent_loop_node(graph)["id"] == "agent_1"

    def test_find_agent_loop_node_absent(self) -> None:
        assert find_agent_loop_node({"nodes": [{"id": "s", "type": "1"}]}) is None
        assert find_agent_loop_node({}) is None


class TestValidateForm:
    def test_valid_form_has_no_issues(self) -> None:
        assert validate_form(_base_form()) == []

    def test_minimal_form_requires_prompt_and_model(self) -> None:
        issues = validate_form({})
        assert any("systemPrompt" in i for i in issues)
        assert any("modleName" in i for i in issues)

    def test_bounds_and_enum(self) -> None:
        issues = validate_form({
            "systemPrompt": "x" * 4001,
            "modleName": "m",
            "maxToolRounds": 51,
            "openingRemarks": "x" * 2001,
            "suggestedQuestions": ["1", "2", "3", "4", "5"],
            "reasoningMode": "chainOfThought",
        })
        assert len(issues) == 5

    def test_datasets_rules(self) -> None:
        issues = validate_form({
            "systemPrompt": "s", "modleName": "m",
            "datasets": [
                {"datasetId": ""},
                {"datasetId": "d2", "mode": "auto"},
                {"datasetId": "d3", "topK": 0},
            ],
        })
        assert any("datasets[0]" in i for i in issues)
        assert any("datasets[1]" in i and "mode" in i for i in issues)
        assert any("datasets[2]" in i and "topK" in i for i in issues)
        too_many = validate_form({
            "systemPrompt": "s", "modleName": "m",
            "datasets": [{"datasetId": f"d{i}"} for i in range(6)],
        })
        assert any("最多" in i for i in too_many)

    def test_reserved_knowledge_tool_prefix(self) -> None:
        issues = validate_form({
            "systemPrompt": "s", "modleName": "m",
            "tools": [{"name": "knowledge_search_1"}],
        })
        assert any("保留前缀" in i for i in issues)


class TestApplyAndRoundTrip:
    def test_apply_writes_literal_shape_and_reads_back(self) -> None:
        """表单写回 → 运行时 convert 口径读出 → 再表单化，与原表单核心字段一致。"""
        node = _agent_node()
        form = _base_form()
        apply_form_to_node(node, form)

        graph = {"nodes": [node], "edges": []}
        found = find_agent_loop_config(graph)
        assert found is not None
        runtime_cfg = found[1]
        assert runtime_cfg["modleName"] == "gpt-4o"
        assert runtime_cfg["datasets"][0]["datasetId"] == "d1"
        assert runtime_cfg["maxToolRounds"] == 8

        re_form = node_config_to_form(runtime_cfg)
        for key in (
            "systemPrompt", "modleName", "maxToolRounds", "tools",
            "datasets", "openingRemarks", "suggestedQuestions", "reasoningMode",
        ):
            assert re_form[key] == form[key], f"round-trip 丢失或变形: {key}"
        assert re_form["memory"]["shortTerm"]["windowTurns"] == 6
        assert re_form["memory"]["shortTerm"]["tokenBudget"] == 1200

    def test_nullable_keys_removed_on_clear(self) -> None:
        """表单清空 plannerPrompt/tokenBudget 时节点键必须物理删除，防"清空仍生效"漂移。"""
        node = _agent_node({
            "plannerPrompt": _literal("旧计划词"),
            "tokenBudget": _literal(999),
        })
        form = _base_form()
        apply_form_to_node(node, form)
        inputs = node["data"]["inputs"]
        assert "plannerPrompt" not in inputs
        assert "tokenBudget" not in inputs

    def test_empty_tools_list_persisted_explicitly(self) -> None:
        """纯聊天 agent：tools 显式写空列表（F2.3），键不能省略。"""
        node = _agent_node({"tools": _literal([{"name": "old"}])})
        form = _base_form()
        form["tools"] = []
        apply_form_to_node(node, form)
        assert node["data"]["inputs"]["tools"] == _literal([])

    def test_defaults_filled_on_read_when_node_sparse(self) -> None:
        """仅有最少键的存量节点读出补齐配置面默认值。"""
        form = node_config_to_form({"modleName": "m", "systemPrompt": "s"})
        assert form["maxToolRounds"] == 10
        assert form["datasets"] == []
        assert form["reasoningMode"] == "react"
        assert form["memory"]["shortTerm"]["enabled"] is True
        assert form["memory"]["shortTerm"]["strategy"] == "truncate"

    def test_plan_execute_reflect_mode_read_back(self) -> None:
        node = _agent_node()
        form = _base_form()
        form["reasoningMode"] = "planExecuteReflect"
        apply_form_to_node(node, form)
        runtime_cfg = find_agent_loop_config({"nodes": [node], "edges": []})[1]
        assert runtime_cfg.get("react_only") in (None, False)
        assert node_config_to_form(runtime_cfg)["reasoningMode"] == "planExecuteReflect"
