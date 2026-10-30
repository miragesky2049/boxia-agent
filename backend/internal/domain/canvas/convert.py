"""画布 JSON → CanvasGraph IR 转换器。

对齐 coze 前端真实输出格式（来源：
  - frontend/packages/workflow/base/src/types/dto.ts
  - backend/domain/workflow/internal/canvas/examples/*.json
）

关键约定：
- 边字段是 sourceNodeID / targetNodeID / sourcePortID（大写 ID），不是小驼峰
- inputs 是混合结构：inputParameters 数组 + 节点特定字段（llmParam / content 等）
- ValueExpressionDTO: {type, value: {type: "literal"|"ref", content, rawMeta}}
- blocks 字段内嵌子图（loop / batch / subworkflow），递归转换
"""

from __future__ import annotations

from typing import Any

from internal.domain.canvas.expression import EnvVar, Expr, GlobalVar, Literal, Ref
from internal.domain.canvas.field_mapping import (
    EDGE_FIELD_MAP,
    NODE_STANDARD_INPUT_FIELDS,
    REF_SOURCE_BLOCK_OUTPUT,
    REF_SOURCE_GLOBAL_PREFIX,
    REF_SOURCE_VARIABLE,
    VALUE_EXPRESSION_TYPES,
)
from internal.domain.canvas.model import (
    CanvasEdge,
    CanvasGraph,
    CanvasNode,
    ErrorPolicy,
    NodeMeta,
    PortSpec,
)
from internal.domain.canvas.node_type import NodeType, UNSUPPORTED_TYPES


class CanvasConvertError(ValueError):
    """画布转换失败。"""


def convert_canvas(raw: dict[str, Any]) -> CanvasGraph:
    """把 coze 画布 JSON 翻译成 CanvasGraph IR。"""
    if not isinstance(raw, dict):
        raise CanvasConvertError("画布根节点必须是对象")
    nodes_raw = raw.get("nodes") or []
    edges_raw = raw.get("edges") or []
    versions = raw.get("versions") or {}

    nodes = [_convert_node(n) for n in nodes_raw]
    edges = [_convert_edge(e) for e in edges_raw]
    return CanvasGraph(nodes=nodes, edges=edges, versions=dict(versions))


def _convert_node(raw: dict[str, Any]) -> CanvasNode:
    node_id = str(raw.get("id") or "")
    if not node_id:
        raise CanvasConvertError("节点缺少 id")

    type_raw = str(raw.get("type") or "")
    try:
        node_type = NodeType(type_raw)
    except ValueError as exc:
        raise CanvasConvertError(f"节点 {node_id} 未知类型: {type_raw}") from exc

    if node_type in UNSUPPORTED_TYPES:
        raise CanvasConvertError(
            f"节点 {node_id} 类型 {node_type.value} ({node_type.name}) 当前阶段不支持"
        )

    data = raw.get("data") or {}
    meta_raw = data.get("nodeMeta") or {}
    position_raw = (raw.get("meta") or {}).get("position") or {}

    meta = NodeMeta(
        title=str(meta_raw.get("title") or ""),
        description=str(meta_raw.get("description") or ""),
        icon=str(meta_raw.get("icon") or ""),
        position=(
            float(position_raw.get("x") or 0),
            float(position_raw.get("y") or 0),
        ),
    )

    outputs = [_convert_port(p) for p in (data.get("outputs") or [])]
    # settingOnError 在 data.inputs 下（不是 data 顶层），先取出来再交给 _convert_inputs 跳过
    raw_inputs = data.get("inputs") or {}
    on_error = _convert_error_policy(raw_inputs.get("settingOnError"))
    inputs, config = _convert_inputs(data, node_type)

    # 递归处理 blocks（loop / batch / subworkflow 内嵌子图）
    subgraph: CanvasGraph | None = None
    blocks = raw.get("blocks") or []
    inner_edges = raw.get("edges") or []
    if blocks:
        subgraph = _convert_subgraph(blocks, inner_edges)

    return CanvasNode(
        id=node_id,
        type=node_type,
        inputs=inputs,
        outputs=outputs,
        config=config,
        meta=meta,
        on_error=on_error,
        subgraph=subgraph,
    )


def _convert_subgraph(
    blocks: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> CanvasGraph:
    """转换内嵌子图（loop/batch/subworkflow 的 blocks + edges）。"""
    nodes = [_convert_node(n) for n in blocks]
    inner_edges = [_convert_edge(e) for e in edges]
    return CanvasGraph(nodes=nodes, edges=inner_edges)


def _convert_port(raw: dict[str, Any]) -> PortSpec:
    return PortSpec(
        name=str(raw.get("name") or ""),
        type=str(raw.get("type") or "string"),
        description=str(raw.get("description") or ""),
        required=bool(raw.get("required", False)),
    )


def _convert_inputs(
    data: dict[str, Any],
    node_type: NodeType,
) -> tuple[dict[str, Expr], dict[str, Any]]:
    """把节点 data.inputs 拆成 (inputs, config) 两部分。

    inputs: {param_name: Expr}  —— 运行时需要求值的参数
    config: 节点特定配置         —— 已经是字面量或结构化配置，不求值

    约定：
    - inputParameters 数组 → inputs
    - llmParam / 其他 *_param 数组 → config（每项已求值为字面量/对象）
    - content / streamingOutput / terminatePlan 这类单值字段 → config
    """
    raw_inputs = data.get("inputs") or {}
    inputs: dict[str, Expr] = {}
    config: dict[str, Any] = {}

    # inputParameters: 统一的运行时入参
    for param in raw_inputs.get("inputParameters") or []:
        name = str(param.get("name") or "")
        if not name:
            continue
        expr = _convert_value_expression(param.get("input"))
        if expr is not None:
            inputs[name] = expr

    # 其余字段按节点类型分派（标准字段跳过，从配置表读取）
    for key, value in raw_inputs.items():
        if key in NODE_STANDARD_INPUT_FIELDS:
            continue
        config[key] = _coerce_config_value(value)

    # 节点特定数组参数（llmParam / 同类 [{name, input: ValueExpressionDTO}]）压成 {name: value}
    _flatten_named_param_lists(config)

    return inputs, config


def _flatten_named_param_lists(config: dict[str, Any]) -> None:
    """把 [{name, input: <值>}] 结构压成 {name: <值>}。

    coze 的 llmParam 等字段是这种结构：[{"name": "temperature", "input": "0.8"}, ...]
    压成 {"temperature": "0.8"} 后，节点 handler 直接 config["temperature"] 取值。
    """
    for key, value in list(config.items()):
        if not isinstance(value, list):
            continue
        if not value or not all(isinstance(item, dict) and "name" in item and "input" in item for item in value):
            continue
        config[key] = {item["name"]: item["input"] for item in value}


def _coerce_config_value(value: Any) -> Any:
    """把 inputs 里非 inputParameters 的字段压成 config。

    - ValueExpressionDTO（{type, value: {...}}）→ 求值成字面量
    - 列表/字典递归处理
    - 其他原样返回
    """
    if _is_value_expression(value):
        expr = _convert_value_expression(value)
        return expr.value if isinstance(expr, Literal) else value
    if isinstance(value, list):
        return [_coerce_config_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _coerce_config_value(v) for k, v in value.items()}
    return value


def _is_value_expression(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and "value" in raw
        and isinstance(raw.get("value"), dict)
        and raw["value"].get("type") in VALUE_EXPRESSION_TYPES
    )


def _convert_value_expression(raw: Any) -> Expr | None:
    """把 ValueExpressionDTO 翻译成 Expr。

    输入形态：
      {type: "string", value: {type: "literal", content: "..."}}
      {type: "string", value: {type: "ref", content: {source, blockID, name}}}
    """
    if not isinstance(raw, dict):
        return None

    value = raw.get("value")
    if not isinstance(value, dict):
        return Literal(value)

    kind = value.get("type")
    content = value.get("content")

    if kind == "literal":
        return Literal(content)

    if kind == "ref":
        if not isinstance(content, dict):
            return Literal(content)
        source = content.get("source")
        block_id = str(content.get("blockID") or "")
        name = str(content.get("name") or "")

        if source == REF_SOURCE_BLOCK_OUTPUT:
            return Ref(block_id=block_id, name=name)
        if source == REF_SOURCE_VARIABLE:
            return GlobalVar(name=name)
        if isinstance(source, str) and source.startswith(REF_SOURCE_GLOBAL_PREFIX):
            return GlobalVar(name=name)
        # 兜底：未知 ref source 按全局变量处理
        return GlobalVar(name=name)

    if kind == "object_ref":
        # 结构化对象引用：暂时原样返回，后续按需展开
        return Literal(content)

    return Literal(content)


def _convert_error_policy(raw: Any) -> ErrorPolicy | None:
    if not isinstance(raw, dict):
        return None
    return ErrorPolicy(
        process_type=int(raw.get("processType") or 0),
        retry_times=int(raw.get("retryTimes") or 0),
        timeout_ms=int(raw.get("timeoutMs") or 180_000),
        data_on_err=str(raw.get("dataOnErr") or ""),
    )


def _convert_edge(raw: dict[str, Any]) -> CanvasEdge:
    """边字段对齐 coze 格式，字段名从配置表读取。"""
    # 用配置表做字段映射
    mapped: dict[str, Any] = {}
    for coze_key, internal_key in EDGE_FIELD_MAP.items():
        if coze_key in raw:
            mapped[internal_key] = raw[coze_key]

    source = str(mapped.get("source") or "")
    target = str(mapped.get("target") or "")
    if not source or not target:
        raise CanvasConvertError(f"边缺少 source/target: {raw}")
    source_port = mapped.get("source_port")
    return CanvasEdge(
        source=source,
        target=target,
        source_port=str(source_port) if source_port else None,
    )
