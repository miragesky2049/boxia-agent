"""最小 workflow 画布工厂：供用户端 workflow 端点测试复用。

产出三幅 coze IR 画布（与管理端落库结构一致）：
- build_start_end_canvas：start→end 直出
- build_start_llm_end_canvas：start→llm→end
- build_start_human_end_canvas：start→human_approval(60)→end

手动启动参数落在 START 的 data.inputs.inputs（与库中真实图一致），
chatflow 内置参数 USER_INPUT / CONVERSATION_NAME 不出现在 workflow 图里。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

START_ID = "100001"
LLM_ID = "123887"
HUMAN_ID = "200001"
END_ID = "900001"


def _node(node_id: str, node_type: str, data: dict[str, Any], x: int, y: int = 0) -> dict[str, Any]:
    return {
        "blocks": [],
        "data": data,
        "edges": None,
        "id": node_id,
        "meta": {"position": {"x": x, "y": y}},
        "type": node_type,
    }


def _edge(source: str, target: str, source_port: str = "") -> dict[str, Any]:
    return {"sourceNodeID": source, "targetNodeID": target, "sourcePortID": source_port}


def _ref_param(name: str, block_id: str, output_name: str, type_: str = "string") -> dict[str, Any]:
    """引用上游节点输出的 inputParameter。"""
    return {
        "name": name,
        "input": {
            "type": type_,
            "value": {
                "content": {"blockID": block_id, "name": output_name, "source": "block-output"},
                "rawMeta": {"type": 1},
                "type": "ref",
            },
        },
    }


def _llm_param(name: str, content: Any, type_: str = "string", raw_type: int = 1) -> dict[str, Any]:
    return {
        "name": name,
        "input": {
            "type": type_,
            "value": {"content": content, "rawMeta": {"type": raw_type}, "type": "literal"},
        },
    }


def _start_node(params: list[dict[str, Any]]) -> dict[str, Any]:
    return _node(
        START_ID,
        "1",
        {
            "nodeMeta": {"title": "开始"},
            "inputs": {"inputs": deepcopy(params), "inputParameters": []},
            "outputs": [],
        },
        0,
    )


def _end_node(params: list[dict[str, Any]], x: int = 920) -> dict[str, Any]:
    return _node(
        END_ID,
        "2",
        {
            "nodeMeta": {"title": "结束"},
            "inputs": {
                "inputParameters": params,
                "streamingOutput": False,
                "terminatePlan": "useAnswerContent",
            },
        },
        x,
    )


def _llm_node() -> dict[str, Any]:
    return _node(
        LLM_ID,
        "3",
        {
            "nodeMeta": {"title": "大模型", "mainColor": "#5C62FF"},
            "inputs": {
                "inputParameters": [_ref_param("input", START_ID, "topic")],
                "llmParam": [
                    _llm_param("modelType", "1737521813", "integer", 2),
                    _llm_param("modleName", "test-model"),
                    _llm_param("generationDiversity", "balance"),
                    _llm_param("temperature", "0.8", "float", 4),
                    _llm_param("maxTokens", "4096", "integer", 2),
                    _llm_param("responseFormat", "2", "integer", 2),
                    _llm_param("prompt", "{{input}}"),
                    _llm_param("systemPrompt", ""),
                ],
                "settingOnError": {"processType": 0, "retryTimes": 0, "timeoutMs": 180000},
            },
            "outputs": [{"name": "output", "type": "string"}],
        },
        460,
    )


def _human_node(assignee_role: str, instructions: str) -> dict[str, Any]:
    return _node(
        HUMAN_ID,
        "60",
        {
            "nodeMeta": {"title": "人审"},
            "inputs": {
                "inputParameters": [_ref_param("content", START_ID, "content")],
                "assignee_role": {
                    "type": "string",
                    "value": {"content": assignee_role, "rawMeta": {"type": 1}, "type": "literal"},
                },
                "instructions": {
                    "type": "string",
                    "value": {"content": instructions, "rawMeta": {"type": 1}, "type": "literal"},
                },
            },
        },
        460,
    )


def _canvas(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"nodes": nodes, "edges": edges, "versions": {"loop": "v2"}}


def start_param(name: str, type_: str = "string", required: bool = True) -> dict[str, Any]:
    """START 手动启动参数描述项。"""
    return {"name": name, "type": type_, "required": required}


def build_start_end_canvas(params: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """start→end：END 直接把启动参数 input 作为 output 返回。"""
    manual = params if params is not None else [start_param("input")]
    nodes = [
        _start_node(manual),
        _end_node([_ref_param("output", START_ID, "input")]),
    ]
    return _canvas(nodes, [_edge(START_ID, END_ID)])


def build_start_llm_end_canvas(params: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """start→llm→end：LLM 读启动参数 topic，END 返回 LLM 的 output。"""
    manual = params if params is not None else [start_param("topic")]
    nodes = [
        _start_node(manual),
        _llm_node(),
        _end_node([_ref_param("output", LLM_ID, "output")]),
    ]
    return _canvas(nodes, [_edge(START_ID, LLM_ID), _edge(LLM_ID, END_ID)])


def build_start_human_end_canvas(
    *,
    assignee_role: str = "leader",
    instructions: str = "请审批该内容",
    params: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """start→human_approval→end：END 取人审节点的 comment。

    中断/续跑依赖 checkpointer，纯转换校验不需要；完整 interrupt/resume
    由 P1 端点集成测试（带数据库 checkpointer）覆盖。
    """
    manual = params if params is not None else [start_param("content")]
    nodes = [
        _start_node(manual),
        _human_node(assignee_role, instructions),
        _end_node([_ref_param("output", HUMAN_ID, "comment")], x=920),
    ]
    return _canvas(nodes, [_edge(START_ID, HUMAN_ID), _edge(HUMAN_ID, END_ID)])
