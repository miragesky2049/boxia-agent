"""canvas convert 层回归测试。

用 coze 真实画布 JSON 样例（tests/fixtures/canvas/）验证 IR 翻译正确性。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.domain.canvas.convert import (
    CanvasConvertError,
    convert_canvas,
    find_agent_loop_config,
)
from internal.domain.canvas.expression import Ref
from internal.domain.canvas.model import CanvasGraph
from internal.domain.canvas.node_type import NodeType

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_convert_start_exit_shape():
    """start_exit.json: START → END，验证基础结构与边字段大小写。"""
    graph = convert_canvas(_load("start_exit.json"))

    assert isinstance(graph, CanvasGraph)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.versions == {"loop": "v2"}

    start = graph.node_by_id("100001")
    end = graph.node_by_id("900001")
    assert start.type == NodeType.START
    assert end.type == NodeType.END

    edge = graph.edges[0]
    assert edge.source == "100001"
    assert edge.target == "900001"
    assert edge.source_port is None or edge.source_port == ""


def test_start_node_outputs():
    """START 节点的 outputs 应解析为 PortSpec 列表。"""
    graph = convert_canvas(_load("start_exit.json"))
    start = graph.node_by_id("100001")

    names = [p.name for p in start.outputs]
    assert "USER_INPUT" in names
    assert "CONVERSATION_NAME" in names
    conversation = next(p for p in start.outputs if p.name == "CONVERSATION_NAME")
    assert conversation.type == "string"


def test_end_node_input_ref_expression():
    """END 节点 inputParameters 里的 ref 应翻译成 Ref(block_id, name)。"""
    graph = convert_canvas(_load("start_exit.json"))
    end = graph.node_by_id("900001")

    assert "output" in end.inputs
    expr = end.inputs["output"]
    assert isinstance(expr, Ref)
    assert expr.block_id == "100001"
    assert expr.name == "USER_INPUT"


def test_convert_llm_chat_three_nodes():
    """llm_chat.json: START → LLM → END，验证 LLM 节点 config 拆分。"""
    graph = convert_canvas(_load("llm_chat.json"))

    assert len(graph.nodes) == 3
    llm = graph.node_by_id("123887")
    assert llm.type == NodeType.LLM

    # LLM 的 inputParameters.input 是对 START.USER_INPUT 的引用
    assert "input" in llm.inputs
    expr = llm.inputs["input"]
    assert isinstance(expr, Ref)
    assert expr.block_id == "100001"
    assert expr.name == "USER_INPUT"


def test_llm_node_config_coerced_to_literal():
    """LLM 的 llmParam 数组应被压成 {name: value} 字典，字面量值已脱壳。"""
    graph = convert_canvas(_load("llm_chat.json"))
    llm = graph.node_by_id("123887")

    # llmParam 是 config 字段（不是运行时入参）
    assert "llmParam" in llm.config
    llm_param = llm.config["llmParam"]
    assert isinstance(llm_param, dict)

    assert llm_param["modleName"] == "豆包·1.5·Pro·32k"
    assert llm_param["temperature"] == "0.8"
    assert llm_param["maxTokens"] == "4096"
    assert llm_param["responseFormat"] == "2"


def test_llm_node_setting_on_error_parsed():
    """LLM 的 settingOnError 应解析为 ErrorPolicy。"""
    graph = convert_canvas(_load("llm_chat.json"))
    llm = graph.node_by_id("123887")

    assert llm.on_error is not None
    assert llm.on_error.process_type == 1
    assert llm.on_error.retry_times == 0
    assert llm.on_error.timeout_ms == 180_000


def test_llm_node_outputs():
    graph = convert_canvas(_load("llm_chat.json"))
    llm = graph.node_by_id("123887")

    assert len(llm.outputs) == 1
    assert llm.outputs[0].name == "output"
    assert llm.outputs[0].type == "string"


def test_unknown_node_type_raises():
    with pytest.raises(CanvasConvertError):
        convert_canvas({"nodes": [{"id": "x", "type": "99999"}], "edges": []})


def test_unsupported_database_node_raises():
    """决策已砍：数据库节点 convert 阶段应显式报错。"""
    with pytest.raises(CanvasConvertError):
        convert_canvas(
            {
                "nodes": [
                    {"id": "1", "type": "1", "data": {}},
                    {"id": "2", "type": "12", "data": {}},  # DATABASE
                ],
                "edges": [{"sourceNodeID": "1", "targetNodeID": "2", "sourcePortID": ""}],
            }
        )


def test_find_agent_loop_config_literal_inputs_shape():
    """前端简化格式：data.inputs.<field> 直接挂 ValueExpressionDTO 字面量。"""
    node_cfg = find_agent_loop_config(
        {
            "nodes": [
                {
                    "id": "loop_1",
                    "type": "100",
                    "data": {
                        "inputs": {
                            "modleName": {"value": {"type": "literal", "content": "m1"}},
                            "tools": {"value": {"type": "literal", "content": [{"name": "t1"}]}},
                        }
                    },
                }
            ],
            "edges": [],
        }
    )
    assert node_cfg is not None
    assert node_cfg[0] == "loop_1"
    assert node_cfg[1]["modleName"] == "m1"


def test_find_agent_loop_config_llm_param_array_shape():
    """coze 真实格式：data.inputs.llmParam 为 [{name, input: ValueExpressionDTO}] 数组。"""
    node_cfg = find_agent_loop_config(
        {
            "nodes": [
                {
                    "id": "loop_1",
                    "type": "100",
                    "data": {
                        "inputs": {
                            "llmParam": [
                                {
                                    "name": "modleName",
                                    "input": {
                                        "type": "string",
                                        "value": {"type": "literal", "content": "m2"},
                                    },
                                },
                            ]
                        }
                    },
                }
            ],
            "edges": [],
        }
    )
    assert node_cfg is not None
    assert node_cfg[1]["llmParam"]["modleName"] == "m2"


def test_find_agent_loop_config_absent_or_unconvertible_returns_none():
    assert (
        find_agent_loop_config({"nodes": [{"id": "s", "type": "1", "data": {}}], "edges": []})
        is None
    )
    # 整图含不支持节点 → 转换失败兜底 None，调用方走各自降级
    assert find_agent_loop_config({"nodes": [{"id": "x", "type": "99999"}], "edges": []}) is None
