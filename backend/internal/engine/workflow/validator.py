"""Workflow 图校验：节点类型白名单、恰好一 start / 一 end、边端点合法、无环。"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

ALLOWED_NODE_TYPES = {"start", "llm", "tool", "end"}


@dataclass(frozen=True)
class GraphValidationError(Exception):
    """图校验失败：message 直接回给上层，前端高亮节点用。"""

    message: str

    def __str__(self) -> str:  # pragma: no cover - Exception 自带 message
        return self.message


def validate_graph(graph: dict[str, Any]) -> None:
    """校验 graph 结构；不合法抛 GraphValidationError。

    调用方（WorkflowService / executor）负责把异常翻译成自己的领域错误。
    """
    if not isinstance(graph, dict):
        raise GraphValidationError("graph 必须是 JSON 对象")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphValidationError("graph.nodes 与 graph.edges 必须为数组")

    node_ids: set[str] = set()
    start_count = 0
    end_count = 0
    indegree: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise GraphValidationError(f"nodes[{index}] 必须为对象")
        node_id = node.get("id")
        node_type = node.get("type")
        if not node_id or not isinstance(node_id, str):
            raise GraphValidationError(f"nodes[{index}].id 必须为非空字符串")
        if node_id in node_ids:
            raise GraphValidationError(f"节点 id 重复：{node_id}")
        node_ids.add(node_id)
        if node_type not in ALLOWED_NODE_TYPES:
            raise GraphValidationError(
                f"节点 {node_id} 类型非法：{node_type}（允许 {sorted(ALLOWED_NODE_TYPES)}）"
            )
        if node_type == "start":
            start_count += 1
        elif node_type == "end":
            end_count += 1

    if start_count != 1:
        raise GraphValidationError(f"必须恰好 1 个 start 节点，当前 {start_count} 个")
    if end_count != 1:
        raise GraphValidationError(f"必须恰好 1 个 end 节点，当前 {end_count} 个")

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise GraphValidationError(f"edges[{index}] 必须为对象")
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids or target not in node_ids:
            raise GraphValidationError(
                f"edges[{index}] 引用了不存在的节点：{source} -> {target}"
            )
        adjacency[source].append(target)
        indegree[target] += 1

    # Kahn 拓扑排序：visited 数 != 节点数 说明存在环
    queue: deque[str] = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for next_node in adjacency[current]:
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                queue.append(next_node)
    if visited != len(node_ids):
        raise GraphValidationError("graph 存在环")


def topological_layers(graph: dict[str, Any]) -> list[list[str]]:
    """按入度分层返回节点 id 列表；同层节点可并行执行。

    前置：必须先调 ``validate_graph`` 保证无环、节点 id 合法。
    """
    indegree: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)
    node_ids: set[str] = set()
    for node in graph.get("nodes") or []:
        node_ids.add(node["id"])
    for edge in graph.get("edges") or []:
        adjacency[edge["source"]].append(edge["target"])
        indegree[edge["target"]] += 1

    layers: list[list[str]] = []
    current = [node_id for node_id in node_ids if indegree[node_id] == 0]
    resolved = set(current)
    while current:
        layers.append(list(current))
        next_layer: list[str] = []
        for node_id in current:
            for next_node in adjacency[node_id]:
                indegree[next_node] -= 1
                if indegree[next_node] == 0 and next_node not in resolved:
                    next_layer.append(next_node)
                    resolved.add(next_node)
        current = next_layer
    return layers
