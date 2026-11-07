"""T17：节点 lint —— 在结构校验之外跑语义级检查。

规则：
1. 表达式语法：config / inputs 里的 `{{...}}` 模板体必须能被 ast.parse(mode="eval") 解析。
2. 必填 config 非空：NodeMeta 里 required=True 的字段在 config 里不能缺失或为空白。
3. 端口类型匹配：每条边 source 输出端口类型 → target 输入端口类型，不兼容时给 warning。
4. 模型引用存在性：调用方传入启用模型目录时，检查 modleName/modelName 在目录内（error）。

返回 list[ValidationIssue]，与 validate_graph 复用同一数据结构。
"""

from __future__ import annotations

import ast
import re
from typing import Any

from internal.domain.canvas.expression import TemplatedString, rewrite_template_refs
from internal.domain.canvas.model import CanvasEdge, CanvasGraph, CanvasNode, PortSpec
from internal.domain.canvas.node_meta import get_node_meta_by_type_code
from internal.domain.canvas.validate import ValidationIssue

_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")

# 变量命名空间引用：{{variables.foo}} / {{system.USER_INPUT}}，兼容 variables['foo']
_NAMESPACE_ATTR_RE = re.compile(r"\b(variables|system)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)")
_NAMESPACE_INDEX_RE = re.compile(r"\b(variables|system)\s*\[\s*['\"]([^'\"]+)['\"]\s*\]")

# 端口类型别名（normalize）
_TYPE_ALIASES: dict[str, str] = {
    "int": "number",
    "integer": "number",
    "float": "number",
    "double": "number",
    "bool": "boolean",
    "str": "string",
    "list": "array",
    "array<string>": "array",
    "array<number>": "array",
    "array<object>": "array",
}


def lint_graph(graph: CanvasGraph) -> list[ValidationIssue]:
    """对 CanvasGraph IR 跑语义级 lint，返回所有 issue。"""
    issues: list[ValidationIssue] = []

    # 供表达式校验重写节点引用（节点 ID 可能含连字符）使用
    ref_names = [n.id for n in graph.nodes] + [v.name for v in graph.variables]

    for node in graph.nodes:
        issues.extend(_lint_node_config(node, ref_names))
        issues.extend(_lint_required_config(node))

    issues.extend(_lint_port_types(graph))
    return issues


# ---------- 1. 表达式语法 ----------
def _lint_node_config(node: CanvasNode, ref_names: list[str]) -> list[ValidationIssue]:
    """递归遍历 node.config，对每个 {{...}} 模板体做 ast.parse 校验。"""
    issues: list[ValidationIssue] = []
    _walk_value(node.config, node.id, issues, ref_names)
    # inputs 里的 TemplatedString 也走一遍
    for expr in node.inputs.values():
        if isinstance(expr, TemplatedString):
            issues.extend(_check_template(node.id, expr.template, ref_names))
    return issues


def _walk_value(
    value: Any,
    node_id: str,
    issues: list[ValidationIssue],
    ref_names: list[str],
) -> None:
    """递归遍历 config，找出字符串模板 / TemplatedString。"""
    if isinstance(value, TemplatedString):
        issues.extend(_check_template(node_id, value.template, ref_names))
        return
    if isinstance(value, str):
        if "{{" in value:
            issues.extend(_check_template(node_id, value, ref_names))
        return
    if isinstance(value, list):
        for item in value:
            _walk_value(item, node_id, issues, ref_names)
        return
    if isinstance(value, dict):
        # 特殊：if_else 节点的 cases[].expression 是裸表达式字符串
        for key, item in value.items():
            if key == "expression" and isinstance(item, str):
                issues.extend(_check_bare_expression(node_id, item, ref_names))
                continue
            _walk_value(item, node_id, issues, ref_names)
        return


def _check_template(
    node_id: str,
    template: str,
    ref_names: list[str],
) -> list[ValidationIssue]:
    """模板字符串：每个 {{...}} 内的表达式都要能解析。"""
    issues: list[ValidationIssue] = []
    for m in _TEMPLATE_RE.finditer(template):
        body = m.group(1).strip()
        if not body:
            issues.append(ValidationIssue(
                "error", "empty_expression",
                f"节点 {node_id} 的模板里有空 {{}} 表达式",
                node_id,
            ))
            continue
        problem = _parse_expression(body, ref_names)
        if problem:
            issues.append(ValidationIssue(
                "error", "expression_syntax",
                f"节点 {node_id} 表达式语法错误 `{body[:60]}`：{problem}",
                node_id,
            ))
    return issues


def _check_bare_expression(
    node_id: str,
    expression: str,
    ref_names: list[str],
) -> list[ValidationIssue]:
    """if case 等场景：整字段就是一个表达式，没有 {{...}} 包裹。"""
    expr = expression.strip()
    if not expr:
        return [ValidationIssue(
            "error", "empty_expression",
            f"节点 {node_id} 的 case 表达式为空",
            node_id,
        )]
    problem = _parse_expression(expr, ref_names)
    if problem:
        return [ValidationIssue(
            "error", "expression_syntax",
            f"节点 {node_id} 表达式语法错误 `{expr[:60]}`：{problem}",
            node_id,
        )]
    return []


def _parse_expression(body: str, ref_names: list[str]) -> str | None:
    """尝试 ast.parse；节点引用先重写成安全别名（节点 ID 可能含连字符）。"""
    source, _ = rewrite_template_refs(body, node_ids=ref_names)
    try:
        ast.parse(source, mode="eval")
        return None
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg}"


# ---------- 2. 必填 config 非空 ----------
def _lint_required_config(node: CanvasNode) -> list[ValidationIssue]:
    meta = get_node_meta_by_type_code(node.type.value)
    if meta is None:
        return []

    issues: list[ValidationIssue] = []
    for field in meta.config_fields:
        if not field.required:
            continue
        value = node.config.get(field.name)
        if _is_empty(value):
            issues.append(ValidationIssue(
                "error", "required_config_empty",
                f"节点 {meta.title}({node.id}) 必填配置项「{field.label}」({field.name}) 为空",
                node.id,
            ))
    return issues


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


# ---------- 3. 未声明变量引用（warning） ----------
def lint_variable_refs(
    graph: CanvasGraph,
    *,
    variable_names: set[str] | None = None,
    system_names: set[str] | None = None,
) -> list[ValidationIssue]:
    """检查 `{{variables.x}}` / `{{system.X}}` 是否引用了未声明变量。

    只在调用方传入声明集合时检查，避免草稿态/离线校验误报。
    严重级别固定为 warning，不阻断保存与发布。
    """
    if variable_names is None and system_names is None:
        return []

    declared_variables = set(variable_names or ()) | {v.name for v in graph.variables}
    declared_system = set(system_names or ())

    issues: list[ValidationIssue] = []
    for node in _iter_nodes(graph):
        seen: set[tuple[str, str]] = set()
        texts = list(_iter_strings(node.config))
        for expr in node.inputs.values():
            if isinstance(expr, TemplatedString):
                texts.append(expr.template)

        for text in texts:
            for namespace, name in _extract_namespace_refs(text):
                key = (namespace, name)
                if key in seen:
                    continue
                seen.add(key)
                if namespace == "variables" and variable_names is not None and name not in declared_variables:
                    issues.append(ValidationIssue(
                        "warning", "undeclared_variable",
                        f"节点 {node.meta.title or node.id} 引用了未声明的应用变量 "
                        f"{{{{variables.{name}}}}}",
                        node.id,
                    ))
                elif namespace == "system" and system_names is not None and name not in declared_system:
                    issues.append(ValidationIssue(
                        "warning", "undeclared_variable",
                        f"节点 {node.meta.title or node.id} 引用了当前形态不支持的系统变量 "
                        f"{{{{system.{name}}}}}",
                        node.id,
                    ))
    return issues


def _iter_nodes(graph: CanvasGraph):
    """递归遍历节点（含 loop/batch/subworkflow 子图）。"""
    for node in graph.nodes:
        yield node
        if node.subgraph is not None:
            yield from _iter_nodes(node.subgraph)


def _iter_strings(value: Any):
    """递归产出 config 中的字符串。"""
    if isinstance(value, TemplatedString):
        yield value.template
    elif isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)


def _extract_namespace_refs(text: str) -> list[tuple[str, str]]:
    refs = [(m.group(1), m.group(2)) for m in _NAMESPACE_ATTR_RE.finditer(text)]
    refs.extend((m.group(1), m.group(2)) for m in _NAMESPACE_INDEX_RE.finditer(text))
    return refs


# ---------- 4. 模型引用存在性（发布闸门） ----------

# coze 画布模型键为 modleName（保留其拼写），兼容旧 modelName；节点 handler 双键读取
_MODEL_CONFIG_KEYS = ("modleName", "modelName")


def lint_model_refs(graph: CanvasGraph, known_models: set[str] | None) -> list[ValidationIssue]:
    """检查节点配置的模型名是否在启用中的模型目录内。

    20261107 复盘（E2E 图片智能体用户端 400）：画布发布了目录中不存在的占位模型，
    运行时才被上游网关拒绝；提前到发布闸门拦截。仅在调用方传入目录集合时检查
    （草稿保存不传，允许编辑中间态）。模型留空跳过（意图/问答节点为可选模型
    兜底），非字符串值（模板表达式）跳过——运行时才求值，无法静态判定。
    """
    if known_models is None:
        return []

    issues: list[ValidationIssue] = []
    for node in _iter_nodes(graph):
        for key in _MODEL_CONFIG_KEYS:
            raw = node.config.get(key)
            if not isinstance(raw, str):
                continue
            model_id = raw.strip()
            if not model_id or model_id in known_models:
                continue
            issues.append(ValidationIssue(
                "error", "unknown_model",
                f"节点 {node.meta.title or node.id} 配置的模型「{model_id}」"
                "不在已启用的模型目录中，请在模型管理中配置该模型或重新选择",
                node.id,
            ))
    return issues


# ---------- 5. 端口类型匹配 ----------
def _lint_port_types(graph: CanvasGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    node_map = {n.id: n for n in graph.nodes}

    for edge in graph.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        if source_node is None or target_node is None:
            continue  # 结构层已经报 dangling

        source_type = _resolve_output_type(source_node, edge.source_port)
        target_type = _resolve_input_type(target_node)

        if source_type == "any" or target_type == "any":
            continue
        if source_type == target_type:
            continue

        # 兼容规则
        compatibility = _check_compatibility(source_type, target_type)
        if compatibility == "ok":
            continue

        severity = "warning"
        code = "port_type_mismatch"
        message = (
            f"边 {edge.source}({source_type}) → {edge.target}({target_type}) 类型不匹配"
        )
        if source_type == "number" and target_type == "boolean":
            message = (
                f"边 {edge.source}({source_type}) → {edge.target}({target_type}) "
                "number 不能直接当 boolean 用（建议显式比较）"
            )
        elif source_type == "boolean" and target_type == "number":
            message = (
                f"边 {edge.source}({source_type}) → {edge.target}({target_type}) "
                "boolean 转 number 会丢失语义"
            )
        issues.append(ValidationIssue(severity, code, message, edge.target))
    return issues


def _resolve_output_type(node: CanvasNode, source_port: str | None) -> str:
    """从节点 outputs 列表或 NodeMeta 默认端口解析输出类型。"""
    if node.outputs:
        for port in node.outputs:
            if source_port is None or port.name == source_port:
                return _normalize_type(port.type)
        return _normalize_type(node.outputs[0].type)

    meta = get_node_meta_by_type_code(node.type.value)
    if meta and meta.outputs:
        for port in meta.outputs:
            if source_port is None or port.name == source_port:
                return _normalize_type(port.type)
        return _normalize_type(meta.outputs[0].type)
    return "any"


def _resolve_input_type(node: CanvasNode) -> str:
    """目标端只要有任意 inputs（用户 inputs 或 NodeMeta 默认），就取第一个的类型。"""
    if node.inputs:
        # CanvasNode.inputs 是 {name: Expr}，没有静态类型；退化为 any
        return "any"
    meta = get_node_meta_by_type_code(node.type.value)
    if meta and meta.inputs:
        return _normalize_type(meta.inputs[0].type)
    return "any"


def _normalize_type(raw: str) -> str:
    t = (raw or "any").strip().lower()
    return _TYPE_ALIASES.get(t, t)


def _check_compatibility(source: str, target: str) -> str:
    """返回 "ok" / "warn"。"""
    if source == "string":
        return "ok"  # string 几乎可以喂给任何字段（运行时强转）
    if source == "any" or target == "any":
        return "ok"
    if source == "object" and target == "string":
        return "ok"
    if source == "array" and target == "object":
        return "warn"
    return "warn"
