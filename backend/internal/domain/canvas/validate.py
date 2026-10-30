"""画布结构校验：save 前检查 graph 是否可执行。

校验规则（只做结构层面，不做业务语义）：
1. START 节点必须存在且唯一
2. 至少有一个 END 节点
3. 所有边的 source/target 必须指向存在的节点
4. 除 START 外的节点必须至少有一条入边（悬空检测）
5. 除 END 外的节点必须至少有一条出边（否则是死端）
6. 环检测：不能有孤立环（不连通 START 的环）

返回 list[ValidationIssue]，空列表表示通过。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from internal.domain.canvas.model import CanvasGraph
from internal.domain.canvas.node_type import NodeType


@dataclass(frozen=True)
class ValidationIssue:
    """校验问题。severity: error=阻塞保存 / warning=仅提示。"""

    severity: str
    code: str
    message: str
    node_id: str = ""


def validate_graph(graph: CanvasGraph) -> list[ValidationIssue]:
    """对 CanvasGraph IR 做结构校验。"""
    issues: list[ValidationIssue] = []

    nodes = graph.nodes
    edges = graph.edges

    # 1. START 节点存在且唯一
    start_nodes = [n for n in nodes if n.type == NodeType.START]
    if not start_nodes:
        issues.append(ValidationIssue("error", "missing_start", "画布缺少 START 节点"))
    elif len(start_nodes) > 1:
        issues.append(ValidationIssue(
            "error", "multiple_start",
            f"画布有 {len(start_nodes)} 个 START 节点，只能有一个",
            start_nodes[0].id,
        ))

    # 2. 至少有一个 END
    end_nodes = [n for n in nodes if n.type == NodeType.END]
    if not end_nodes:
        issues.append(ValidationIssue("warning", "missing_end", "画布缺少 END 节点"))

    # 3. 边引用的节点必须存在
    node_ids = {n.id for n in nodes}
    for edge in edges:
        if edge.source not in node_ids:
            issues.append(ValidationIssue(
                "error", "dangling_edge_source",
                f"边的 source 节点不存在: {edge.source}",
                edge.source,
            ))
        if edge.target not in node_ids:
            issues.append(ValidationIssue(
                "error", "dangling_edge_target",
                f"边的 target 节点不存在: {edge.target}",
                edge.target,
            ))

    # 4/5. 悬空 / 死端检测
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}
    out_degree: dict[str, int] = {n.id: 0 for n in nodes}
    for edge in edges:
        if edge.source in out_degree:
            out_degree[edge.source] += 1
        if edge.target in in_degree:
            in_degree[edge.target] += 1

    for n in nodes:
        if n.type != NodeType.START and in_degree[n.id] == 0:
            issues.append(ValidationIssue(
                "error", "no_incoming_edge",
                f"节点 {n.meta.title or n.id} 没有入边",
                n.id,
            ))
        if n.type != NodeType.END and out_degree[n.id] == 0:
            issues.append(ValidationIssue(
                "warning", "no_outgoing_edge",
                f"节点 {n.meta.title or n.id} 没有出边，执行后会中断",
                n.id,
            ))

    # 6. 环检测：从 START DFS，未访问到的节点构成孤立子图
    if start_nodes:
        reachable = _reachable_from(start_nodes[0].id, out_degree, edges)
        for n in nodes:
            if n.id not in reachable:
                issues.append(ValidationIssue(
                    "warning", "unreachable_node",
                    f"节点 {n.meta.title or n.id} 从 START 不可达（孤立子图或环）",
                    n.id,
                ))

    return issues


def _reachable_from(start_id: str, out_degree: dict[str, int], edges: list) -> set[str]:
    """从 start_id 出发 DFS 可达的所有节点。"""
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    visited: set[str] = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for next_id in adjacency.get(current, []):
            if next_id not in visited:
                stack.append(next_id)
    return visited


def validate_raw_graph(raw: dict[str, Any]) -> list[ValidationIssue]:
    """对原始 dict graph 做校验：先 convert 成 IR，再 validate。

    convert 失败时返回 error 级问题。用于 save_graph 前的快速校验。
    """
    from internal.domain.canvas.convert import CanvasConvertError, convert_canvas

    try:
        graph = convert_canvas(raw)
    except CanvasConvertError as exc:
        return [ValidationIssue("error", "convert_failed", str(exc))]
    except Exception as exc:  # noqa: BLE001
        return [ValidationIssue("error", "convert_failed", f"画布解析失败: {exc}")]

    return validate_graph(graph)
