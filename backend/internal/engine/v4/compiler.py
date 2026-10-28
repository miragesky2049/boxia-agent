"""LangGraph 编译层：把画布 JSON 直接编译成 LangGraph StateGraph。"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import StateGraph

from internal.engine.v4.registry import get_node

logger = logging.getLogger(__name__)


def infer_runtime_mode(graph: dict[str, Any]) -> str:
    """根据 graph 结构自动推断运行模式：dag / agent_loop。"""
    has_loop_edge = any(
        edge.get("type") == "feedback" or edge["from"] == edge["to"]
        for edge in graph.get("edges", [])
    )
    has_agent_node = any(
        node["type"] == "agent_loop" for node in graph.get("nodes", [])
    )
    return "agent_loop" if (has_loop_edge or has_agent_node) else "dag"


def compile_graph(graph: dict[str, Any]):
    """把画布 JSON 编译成可执行的 LangGraph graph。

    不做翻译，画布直接产出 LangGraph 兼容定义。
    返回 sg.compile() 后的可执行对象。
    """
    state_schema = _build_state_schema(graph)
    sg = StateGraph(state_schema)

    # 注册节点
    node_fns: dict[str, Callable] = {}
    for node in graph.get("nodes", []):
        plugin = get_node(node["type"])
        node_fn = plugin.build(node.get("config", {}))
        node_fns[node["id"]] = node_fn
        sg.add_node(node["id"], node_fn)

    # 注册边
    for edge in graph.get("edges", []):
        source = edge["from"]
        target = edge["to"]
        source_fn = node_fns.get(source)

        # 如果源节点是 branch 且带 router，用条件路由
        if hasattr(source_fn, "__router__"):
            sg.add_conditional_edges(
                source,
                source_fn.__router__,
                {target: target},
            )
        elif "when" in edge:
            sg.add_conditional_edges(
                source,
                _build_router(edge["when"]),
                {target: target},
            )
        else:
            sg.add_edge(source, target)

    # 找入口节点
    start_nodes = [n for n in graph["nodes"] if n["type"] == "start"]
    if not start_nodes:
        raise ValueError("graph 缺少 start 节点")
    sg.set_entry_point(start_nodes[0]["id"])

    return sg.compile()


def _build_state_schema(graph: dict[str, Any]) -> type:
    """从 graph 的 state_schema 定义构建 LangGraph state 类型。"""
    # v4 首期：用 TypedDict 简化，后续支持动态 schema
    from typing import TypedDict

    class WorkflowState(TypedDict, total=False):
        messages: list
        input: dict
        output: dict

    return WorkflowState


def _build_router(when: str):
    """构建条件路由函数。"""

    def router(state: dict) -> str:
        # v4 首期：简单实现，后续扩展条件表达式
        return state.get("route", when)

    return router
