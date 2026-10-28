"""节点类型注册表：把 graph JSON 里的 type 字符串映射到运行期节点类。"""

from __future__ import annotations

from typing import Any, Callable

from internal.engine.llm import LLMClient
from internal.engine.workflow.nodes import (
    EndNode,
    LLMNode,
    StartNode,
    ToolNode,
    WorkflowNode,
)


def build_node(
    node_id: str,
    node_type: str,
    data: dict[str, Any] | None,
    llm_factory: Callable[[dict[str, Any]], LLMClient],
) -> WorkflowNode:
    """按类型构造运行期节点实例。"""
    if node_type == "start":
        return StartNode(node_id, data)
    if node_type == "llm":
        return LLMNode(node_id, data, llm_factory)
    if node_type == "tool":
        return ToolNode(node_id, data)
    if node_type == "end":
        return EndNode(node_id, data)
    raise ValueError(f"未知节点类型：{node_type}")
