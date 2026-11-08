"""0074 PRD F2：智能体配置表单 ⇄ 画布节点映射单测（domain/canvas/agent_config）。"""

from __future__ import annotations

from internal.domain.agent.memory import parse_long_term_config, parse_memory_config
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

    def test_long_term_bounds_and_admin_gate(self) -> None:
        """M4 F16.1/F16.6：longTerm 越界显式报错；管理面未部署时拒绝开启。"""
        base = _base_form()
        base["memory"] = {
            "shortTerm": {},
            "longTerm": {"enabled": True, "recallTopK": 21, "maxMemories": 5},
        }
        issues = validate_form(base)
        assert any("recallTopK" in i for i in issues)
        assert any("maxMemories" in i for i in issues)
        # 默认管理面已部署：enabled 不报错
        assert validate_form(base, long_term_admin_available=True) == issues
        gated = validate_form(base, long_term_admin_available=False)
        assert any("管理面未部署" in i for i in gated)
        # 关闭态不触发隐私闸门
        base["memory"]["longTerm"]["enabled"] = False
        assert not any("管理面" in i for i in validate_form(base, long_term_admin_available=False))
        # review 修正：bool/float/字符串都不是合法"整数"输入，必须显式报错
        base["memory"]["longTerm"] = {"enabled": False, "recallTopK": True, "maxMemories": 8.9}
        strict = validate_form(base)
        assert any("recallTopK" in i for i in strict)
        assert any("maxMemories" in i for i in strict)

    def test_bounds_and_enum(self) -> None:
        issues = validate_form(
            {
                "systemPrompt": "x" * 4001,
                "modleName": "m",
                "maxToolRounds": 51,
                "openingRemarks": "x" * 2001,
                "suggestedQuestions": ["1", "2", "3", "4", "5"],
                "reasoningMode": "chainOfThought",
            }
        )
        assert len(issues) == 5

    def test_datasets_rules(self) -> None:
        issues = validate_form(
            {
                "systemPrompt": "s",
                "modleName": "m",
                "datasets": [
                    {"datasetId": ""},
                    {"datasetId": "d2", "mode": "auto"},
                    {"datasetId": "d3", "topK": 0},
                ],
            }
        )
        assert any("datasets[0]" in i for i in issues)
        assert any("datasets[1]" in i and "mode" in i for i in issues)
        assert any("datasets[2]" in i and "topK" in i for i in issues)
        too_many = validate_form(
            {
                "systemPrompt": "s",
                "modleName": "m",
                "datasets": [{"datasetId": f"d{i}"} for i in range(6)],
            }
        )
        assert any("最多" in i for i in too_many)

    def test_reserved_knowledge_tool_prefix(self) -> None:
        issues = validate_form(
            {
                "systemPrompt": "s",
                "modleName": "m",
                "tools": [{"name": "knowledge_search_1"}],
            }
        )
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
            "systemPrompt",
            "modleName",
            "maxToolRounds",
            "tools",
            "datasets",
            "openingRemarks",
            "suggestedQuestions",
            "reasoningMode",
        ):
            assert re_form[key] == form[key], f"round-trip 丢失或变形: {key}"
        assert re_form["memory"]["shortTerm"]["windowTurns"] == 6
        assert re_form["memory"]["shortTerm"]["tokenBudget"] == 1200

    def test_memory_summarize_keys_round_trip_parity(self) -> None:
        """M4 PRD F15.1 / C4：summarize 新键在 表单→节点→运行时口径→再表单化
        全链路同构归一（表单面与 ChatService 消费面解析结果必须逐键一致）。"""
        node = _agent_node()
        form = _base_form()
        form["memory"] = {
            "shortTerm": {
                "enabled": True,
                "strategy": "summarize",
                "keepRecentTurns": 8,
                "summarizeModel": "lite-m",
                "maxSummaryChars": 900,
            }
        }
        apply_form_to_node(node, form)

        found = find_agent_loop_config({"nodes": [node], "edges": []})
        assert found is not None
        runtime_cfg = found[1]
        re_form = node_config_to_form(runtime_cfg)
        parsed = parse_memory_config(form["memory"])
        assert parsed["strategy"] == "summarize"
        assert parsed["keepRecentTurns"] == 8
        assert parsed["summarizeModel"] == "lite-m"
        assert parsed["maxSummaryChars"] == 900
        # M4 F16.1 后表单恒携带 longTerm 键组（未配置=默认关闭态）
        assert re_form["memory"] == {
            "shortTerm": parsed,
            "longTerm": parse_long_term_config(form["memory"]),
        }
        # 运行时消费面（ChatService._load_agent_memory 同源解析）与表单面一致
        assert parse_memory_config(runtime_cfg.get("memory")) == parsed

    def test_long_term_keys_round_trip_parity(self) -> None:
        """M4 PRD F16.1 / C4：longTerm 键组在 表单→节点→运行时口径→再表单化
        全链路同构归一，关闭态恒写出显式 false。"""
        node = _agent_node()
        form = _base_form()
        form["memory"] = {
            "shortTerm": {"strategy": "summarize", "keepRecentTurns": 8},
            "longTerm": {
                "enabled": True,
                "extractModel": "cheap-m",
                "recallTopK": 8,
                "maxMemories": 50,
            },
        }
        apply_form_to_node(node, form)
        assert node["data"]["inputs"]["memory"] == _literal(
            {
                "shortTerm": parse_memory_config(form["memory"]),
                "longTerm": parse_long_term_config(form["memory"]),
            }
        )

        found = find_agent_loop_config({"nodes": [node], "edges": []})
        assert found is not None
        runtime_cfg = found[1]
        re_form = node_config_to_form(runtime_cfg)
        parsed = parse_long_term_config(form["memory"])
        assert parsed == {
            "enabled": True,
            "extractModel": "cheap-m",
            "recallTopK": 8,
            "maxMemories": 50,
        }
        assert re_form["memory"]["longTerm"] == parsed
        # 运行时消费面（ChatService._build_chat_run_plan 同源解析）与表单面一致
        assert parse_long_term_config(runtime_cfg.get("memory")) == parsed

    def test_long_term_disabled_written_explicitly(self) -> None:
        """表单未携带 longTerm：写回节点落显式默认关闭态，杜绝键漂移。"""
        node = _agent_node()
        apply_form_to_node(node, _base_form())
        written = node["data"]["inputs"]["memory"]["value"]["content"]
        assert written["longTerm"] == {
            "enabled": False,
            "extractModel": None,
            "recallTopK": 5,
            "maxMemories": 200,
        }

    def test_nullable_keys_removed_on_clear(self) -> None:
        """表单清空 plannerPrompt/tokenBudget 时节点键必须物理删除，防"清空仍生效"漂移。"""
        node = _agent_node(
            {
                "plannerPrompt": _literal("旧计划词"),
                "tokenBudget": _literal(999),
            }
        )
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


class TestMcpSessionConfig:
    """M4-b T-b3：mcpServers[].timeoutSeconds / mcpSession.scope 校验与四处同构。"""

    @staticmethod
    def _form_with_mcp(
        server_extra: dict | None = None,
        mcp_session: object = None,
    ) -> dict:
        server = {
            "serverUrl": "https://m.example.com/mcp",
            "name": "地图",
            "enabledTools": [{"name": "geocode"}],
        }
        server.update(server_extra or {})
        form = _base_form()
        form["mcpServers"] = [server]
        if mcp_session is not None:
            form["mcpSession"] = mcp_session
        return form

    def test_valid_timeout_and_scope(self) -> None:
        assert validate_form(self._form_with_mcp({"timeoutSeconds": 5}, {"scope": "run"})) == []
        assert validate_form(self._form_with_mcp(None, {"scope": "conversation"})) == []
        # 缺省不写 timeoutSeconds 合法（运行期回落默认 30）
        assert validate_form(self._form_with_mcp()) == []

    def test_timeout_bounds_reject_dirty_values(self) -> None:
        for bad in (0, 301, "abc", True, 1.5):
            issues = validate_form(self._form_with_mcp({"timeoutSeconds": bad}))
            assert any("timeoutSeconds" in issue for issue in issues), bad

    def test_scope_enum_and_shape(self) -> None:
        issues = validate_form(self._form_with_mcp(mcp_session={"scope": "global"}))
        assert any("mcpSession.scope" in issue for issue in issues)
        assert any(
            "mcpSession" in issue for issue in validate_form(self._form_with_mcp(mcp_session="run"))
        )

    def test_mcp_keys_round_trip_parity(self) -> None:
        node = _agent_node()
        apply_form_to_node(
            node, self._form_with_mcp({"timeoutSeconds": 45}, {"scope": "conversation"})
        )
        inputs = node["data"]["inputs"]
        assert inputs["mcpServers"]["value"]["content"][0]["timeoutSeconds"] == 45
        assert inputs["mcpSession"]["value"]["content"] == {"scope": "conversation"}

        runtime_cfg = find_agent_loop_config({"nodes": [node], "edges": []})[1]
        re_form = node_config_to_form(runtime_cfg)
        assert re_form["mcpSession"] == {"scope": "conversation"}
        assert re_form["mcpServers"][0]["timeoutSeconds"] == 45
        # 再应用一次：值不回漂
        node2 = _agent_node()
        apply_form_to_node(node2, re_form)
        assert node2["data"]["inputs"]["mcpSession"] == _literal({"scope": "conversation"})

    def test_api_payload_preserves_mcp_session(self) -> None:
        """T-b7 回归：AgentConfigPayload 曾缺 mcpSession 键，Pydantic 丢弃未知键
        导致 PUT 静默丢档；此处锁定 API 边界 → 域写回的完整链路。"""
        from web.admin.schemas.apps import AgentConfigPayload

        form = self._form_with_mcp({"timeoutSeconds": 45}, {"scope": "conversation"})
        dumped = AgentConfigPayload(**form).model_dump()
        assert dumped["mcpSession"] == {"scope": "conversation"}

        node = _agent_node()
        apply_form_to_node(node, dumped)
        assert node["data"]["inputs"]["mcpSession"] == _literal({"scope": "conversation"})
        assert node["data"]["inputs"]["mcpServers"]["value"]["content"][0]["timeoutSeconds"] == 45

    def test_legacy_graph_defaults_to_run_scope(self) -> None:
        """历史图无 mcpSession 键 / 携带非法 scope：表单化补默认 run，不抛错。"""
        legacy = _agent_node({"mcpServers": _literal([{"serverUrl": "https://x/mcp"}])})
        assert node_config_to_form(legacy["data"]["inputs"])["mcpSession"] == {"scope": "run"}
        weird = _agent_node({"mcpSession": _literal({"scope": "weird"})})
        assert node_config_to_form(weird["data"]["inputs"])["mcpSession"] == {"scope": "run"}


class TestSubAgentsConfig:
    """M4-c F14.1：subAgents 协作挂载校验与表单⇄config 三处同构。"""

    _OTHER = "7b2e3d4c-0000-0000-0000-000000000002"

    @staticmethod
    def _form_with_sub(*entries: dict, count: int | None = None) -> dict:
        if count is not None:
            items = [
                {"applicationId": f"aa00000{i}00-0000-0000-0000-000000000000"}
                for i in range(1, count + 1)
            ]
        else:
            items = list(entries)
        form = _base_form()
        form["subAgents"] = items
        return form

    def test_valid_entries(self) -> None:
        assert (
            validate_form(
                self._form_with_sub(
                    {"applicationId": self._OTHER, "mode": "delegate"},
                    {"applicationId": "aaaaaaaa-1111-2222-3333-444444444444", "mode": "handoff"},
                    # mode 缺省合法（运行期回落 delegate）
                    {"applicationId": "bbbbbbbb-1111-2222-3333-444444444444"},
                )
            )
            == []
        )

    def test_cap_rejects_sixth_entry(self) -> None:
        issues = validate_form(self._form_with_sub(count=6))
        assert any("subAgents 最多 5 个" in issue for issue in issues)

    def test_entry_rules(self) -> None:
        issues = validate_form(
            self._form_with_sub(
                {"applicationId": ""},
                {"applicationId": "not-a-uuid"},
                {"applicationId": self._OTHER, "mode": "escalate"},
                {"applicationId": self._OTHER},
            )
        )
        assert any("subAgents[0] 缺少 applicationId" in issue for issue in issues)
        assert any("subAgents[1]" in issue and "UUID" in issue for issue in issues)
        assert any("subAgents[2]" in issue and "mode" in issue for issue in issues)
        assert any("subAgents[3]" in issue and "重复" in issue for issue in issues)

    def test_tool_name_reserves_hand_back(self) -> None:
        # 批末 review #5：hand_back 为内核保留归位工具名，挂载自定义 toolName 撞名
        # 会导致专家接管轮跳过归位注入（agent_loop 撞名静默让位），配置面必须拒绝
        issues = validate_form(
            self._form_with_sub({"applicationId": self._OTHER, "toolName": "hand_back"})
        )
        assert any("subAgents[0].toolName" in issue and "hand_back" in issue for issue in issues)

    def test_self_reference_rejected_when_context_given(self) -> None:
        form = self._form_with_sub({"applicationId": self._OTHER})
        issues = validate_form(form, self_application_id=self._OTHER)
        assert any("自引用" in issue for issue in issues)
        # 不传上下文（旁路调用）保持结构校验语义
        assert validate_form(form) == []

    def test_tool_name_override_cannot_use_synth_prefix(self) -> None:
        issues = validate_form(
            self._form_with_sub(
                {"applicationId": self._OTHER, "toolName": "workflow_1"},
            )
        )
        assert any("toolName" in issue for issue in issues)
        # agent_ 前缀是合成名自家口径，覆盖值允许（非保留冲突面）
        assert (
            validate_form(
                self._form_with_sub(
                    {"applicationId": self._OTHER, "toolName": "ask_expense_bot"},
                )
            )
            == []
        )

    def test_tools_agent_prefix_reserved(self) -> None:
        """F14.3：agent_ 保留前缀三处同构——用户基础工具不得占用。"""
        form = _base_form()
        form["tools"] = [{"name": "agent_sneaky", "description": "d", "parameters": {}}]
        issues = validate_form(form)
        assert any("agent_" in issue for issue in issues)

    def test_sub_agents_round_trip_parity(self) -> None:
        node = _agent_node()
        apply_form_to_node(
            node,
            self._form_with_sub(
                {
                    "applicationId": self._OTHER,
                    "mode": "handoff",
                    "toolName": "expert_b",
                    "description": "报销",
                },
            ),
        )
        assert node["data"]["inputs"]["subAgents"] == _literal(
            [
                {
                    "applicationId": self._OTHER,
                    "mode": "handoff",
                    "toolName": "expert_b",
                    "description": "报销",
                },
            ]
        )

        runtime_cfg = find_agent_loop_config({"nodes": [node], "edges": []})[1]
        re_form = node_config_to_form(runtime_cfg)
        assert re_form["subAgents"] == [
            {
                "applicationId": self._OTHER,
                "mode": "handoff",
                "toolName": "expert_b",
                "description": "报销",
            },
        ]
        node2 = _agent_node()
        apply_form_to_node(node2, re_form)
        assert node2["data"]["inputs"]["subAgents"] == node["data"]["inputs"]["subAgents"]

    def test_api_payload_preserves_sub_agents(self) -> None:
        """T-c3 回归：payload 必须显式承载 subAgents（同 mcpSession 缺键丢档教训）。"""
        from web.admin.schemas.apps import AgentConfigPayload

        form = self._form_with_sub({"applicationId": self._OTHER, "mode": "delegate"})
        dumped = AgentConfigPayload(**form).model_dump()
        assert dumped["subAgents"] == [{"applicationId": self._OTHER, "mode": "delegate"}]

        node = _agent_node()
        apply_form_to_node(node, dumped)
        assert node["data"]["inputs"]["subAgents"] == _literal(dumped["subAgents"])

    def test_legacy_graph_defaults_to_empty_list(self) -> None:
        legacy = _agent_node({"systemPrompt": _literal("S")})
        assert node_config_to_form(legacy["data"]["inputs"])["subAgents"] == []


class TestQualityGateConfig:
    """M4-d T-d7 F19.2：qualityGate 键组校验与表单⇄config⇄API 四处同构。"""

    _DEFAULT_GATE = {
        "enabled": False,
        "judgeModel": "",
        "rubric": "",
        "passScore": 7,
        "maxRegen": 1,
    }

    def test_valid_quality_gate_accepted(self) -> None:
        form = _base_form()
        form["qualityGate"] = {
            "enabled": True,
            "judgeModel": "judge-m",
            "rubric": "必须引用知识库出处",
            "passScore": 8,
            "maxRegen": 2,
        }
        assert validate_form(form) == []
        # 缺键合法（= 门关闭默认组）
        assert validate_form(_base_form()) == []

    def test_shape_and_bounds_rejected(self) -> None:
        form = _base_form()
        form["qualityGate"] = "on"
        assert any("qualityGate" in issue for issue in validate_form(form))

        for bad_score in (11, -1, "8", True, 8.5):
            form = _base_form()
            form["qualityGate"] = {"enabled": True, "passScore": bad_score}
            issues = validate_form(form)
            assert any("passScore" in issue for issue in issues), bad_score

        # maxRegen 允许 0（只评不重生），上界 2
        form = _base_form()
        form["qualityGate"] = {"enabled": True, "maxRegen": 0}
        assert validate_form(form) == []
        for bad_regen in (3, -1, "1", False, 1.5):
            form = _base_form()
            form["qualityGate"] = {"enabled": True, "maxRegen": bad_regen}
            issues = validate_form(form)
            assert any("maxRegen" in issue for issue in issues), bad_regen

    def test_rubric_length_limit(self) -> None:
        form = _base_form()
        form["qualityGate"] = {"enabled": True, "rubric": "长" * 2001}
        assert any("rubric" in issue for issue in validate_form(form))

    def test_enabled_and_judge_model_types_rejected(self) -> None:
        """批末 review P2-3：校验覆盖全键——enabled/judgeModel 脏类型不得被归一
        静默洗成 True/""（"false" 字符串 bool() 为真会误开门）。"""
        form = _base_form()
        form["qualityGate"] = {"enabled": "false"}
        assert any("qualityGate.enabled" in issue for issue in validate_form(form))

        form = _base_form()
        form["qualityGate"] = {"enabled": True, "judgeModel": 123}
        assert any("qualityGate.judgeModel" in issue for issue in validate_form(form))

    def test_quality_gate_round_trip_parity(self) -> None:
        gate = {
            "enabled": True,
            "judgeModel": "judge-m",
            "rubric": "三段准则",
            "passScore": 9,
            "maxRegen": 2,
        }
        node = _agent_node()
        apply_form_to_node(node, {**_base_form(), "qualityGate": gate})
        assert node["data"]["inputs"]["qualityGate"] == _literal(gate)

        runtime_cfg = find_agent_loop_config({"nodes": [node], "edges": []})[1]
        re_form = node_config_to_form(runtime_cfg)
        assert re_form["qualityGate"] == gate
        node2 = _agent_node()
        apply_form_to_node(node2, re_form)
        assert node2["data"]["inputs"]["qualityGate"] == _literal(gate)

    def test_legacy_graph_defaults_to_closed_gate(self) -> None:
        legacy = _agent_node({"systemPrompt": _literal("S")})
        assert node_config_to_form(legacy["data"]["inputs"])["qualityGate"] == self._DEFAULT_GATE
        weird = _agent_node(
            {"qualityGate": _literal({"enabled": True, "passScore": 99, "maxRegen": -3})}
        )
        # 与生产读路径一致：先经转换层脱 literal，再表单化（直接喂 wrapper 会键名错位）
        runtime_cfg = find_agent_loop_config({"nodes": [weird], "edges": []})[1]
        normalized = node_config_to_form(runtime_cfg)["qualityGate"]
        assert normalized == {
            "enabled": True,
            "judgeModel": "",
            "rubric": "",
            "passScore": 7,
            "maxRegen": 1,
        }

    def test_apply_normalizes_missing_gate_to_closed_defaults(self) -> None:
        node = _agent_node()
        apply_form_to_node(node, _base_form())
        assert node["data"]["inputs"]["qualityGate"] == _literal(self._DEFAULT_GATE)

    def test_api_payload_preserves_quality_gate(self) -> None:
        """同类 T-b7 缺陷防御：AgentConfigPayload 缺键会让 PUT 静默丢门配置。"""
        from web.admin.schemas.apps import AgentConfigPayload

        gate = {"enabled": True, "passScore": 8}
        dumped = AgentConfigPayload(**{**_base_form(), "qualityGate": gate}).model_dump()
        assert dumped["qualityGate"] == gate

        node = _agent_node()
        apply_form_to_node(node, dumped)
        assert node["data"]["inputs"]["qualityGate"]["value"]["content"]["passScore"] == 8


class TestJudgeSamplingConfig:
    """M4-d T-d8 F19.3：judgeSampling 键组校验与四处同构（采样只观测不干预）。"""

    _DEFAULT_SAMPLING = {"enabled": False, "rate": 0.1, "judgeModel": "", "rubric": ""}

    def test_valid_sampling_accepted(self) -> None:
        form = _base_form()
        form["judgeSampling"] = {
            "enabled": True,
            "rate": 0.3,
            "judgeModel": "judge-m",
            "rubric": "事实性以检索结果为准",
        }
        assert validate_form(form) == []
        # 缺键合法（= 采样关闭默认组）
        assert validate_form(_base_form()) == []

    def test_shape_and_bounds_rejected(self) -> None:
        form = _base_form()
        form["judgeSampling"] = "on"
        assert any("judgeSampling" in issue for issue in validate_form(form))

        form = _base_form()
        form["judgeSampling"] = {"enabled": "true"}
        assert any("judgeSampling.enabled" in issue for issue in validate_form(form))

        for bad_rate in (-0.1, 1.1, "0.5", True):
            form = _base_form()
            form["judgeSampling"] = {"enabled": True, "rate": bad_rate}
            assert any("judgeSampling.rate" in issue for issue in validate_form(form)), bad_rate

        form = _base_form()
        form["judgeSampling"] = {"enabled": True, "judgeModel": 123}
        assert any("judgeSampling.judgeModel" in issue for issue in validate_form(form))

        form = _base_form()
        form["judgeSampling"] = {"enabled": True, "rubric": "长" * 2001}
        assert any("judgeSampling.rubric" in issue for issue in validate_form(form))

        # rate 边界值合法：0.0（恒不投）与 1.0（必投）
        form = _base_form()
        form["judgeSampling"] = {"enabled": True, "rate": 0.0}
        assert validate_form(form) == []
        form["judgeSampling"] = {"enabled": True, "rate": 1.0}
        assert validate_form(form) == []

    def test_sampling_round_trip_parity(self) -> None:
        sampling = {"enabled": True, "rate": 0.25, "judgeModel": "judge-m", "rubric": "三段准则"}
        node = _agent_node()
        apply_form_to_node(node, {**_base_form(), "judgeSampling": sampling})
        assert node["data"]["inputs"]["judgeSampling"] == _literal(sampling)

        runtime_cfg = find_agent_loop_config({"nodes": [node], "edges": []})[1]
        re_form = node_config_to_form(runtime_cfg)
        assert re_form["judgeSampling"] == sampling
        node2 = _agent_node()
        apply_form_to_node(node2, re_form)
        assert node2["data"]["inputs"]["judgeSampling"] == _literal(sampling)

    def test_legacy_graph_defaults_to_closed_sampling(self) -> None:
        legacy = _agent_node({"systemPrompt": _literal("S")})
        assert (
            node_config_to_form(legacy["data"]["inputs"])["judgeSampling"] == self._DEFAULT_SAMPLING
        )
        weird = _agent_node({"judgeSampling": _literal({"enabled": True, "rate": 9.9})})
        runtime_cfg = find_agent_loop_config({"nodes": [weird], "edges": []})[1]
        normalized = node_config_to_form(runtime_cfg)["judgeSampling"]
        assert normalized == {"enabled": True, "rate": 0.1, "judgeModel": "", "rubric": ""}

    def test_apply_normalizes_missing_sampling_to_closed_defaults(self) -> None:
        node = _agent_node()
        apply_form_to_node(node, _base_form())
        assert node["data"]["inputs"]["judgeSampling"] == _literal(self._DEFAULT_SAMPLING)

    def test_api_payload_preserves_judge_sampling(self) -> None:
        """T-b7/T-d7 同类缺陷防御：Payload 缺 judgeSampling 键会让 PUT 静默丢采样配置。"""
        from web.admin.schemas.apps import AgentConfigPayload

        sampling = {"enabled": True, "rate": 1.0}
        dumped = AgentConfigPayload(**{**_base_form(), "judgeSampling": sampling}).model_dump()
        assert dumped["judgeSampling"] == sampling

        node = _agent_node()
        apply_form_to_node(node, dumped)
        assert node["data"]["inputs"]["judgeSampling"]["value"]["content"]["rate"] == 1.0
