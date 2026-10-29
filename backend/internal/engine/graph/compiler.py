"""LangGraph 编译层：把画布 JSON 直接编译成 LangGraph StateGraph。"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from internal.engine.graph.registry import get_node

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


def compile_graph(graph: dict[str, Any], checkpointer: Any = None):
    """把画布 JSON 编译成可执行的 LangGraph graph。

    不做翻译，画布直接产出 LangGraph 兼容定义。
    如果传了 checkpointer，编译时挂上，支持 interrupt / resume（人审节点）。
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

    # 按 source 分组收集出边，便于 branch 节点合并条件路由
    edges_by_source: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []):
        edges_by_source.setdefault(edge["from"], []).append(edge)

    # 注册边：普通节点直接 add_edge；带 __router__ 的 branch 节点合并所有出边为一次 conditional_edges
    for source, out_edges in edges_by_source.items():
        source_fn = node_fns.get(source)
        if hasattr(source_fn, "__router__"):
            path_map = {edge["to"]: edge["to"] for edge in out_edges}
            sg.add_conditional_edges(source, source_fn.__router__, path_map)
        else:
            for edge in out_edges:
                sg.add_edge(source, edge["to"])

    # 找入口节点
    start_nodes = [n for n in graph["nodes"] if n["type"] == "start"]
    if not start_nodes:
        raise ValueError("graph 缺少 start 节点")
    sg.set_entry_point(start_nodes[0]["id"])

    # 所有 end 节点自动连 END；没有出边的节点也视为终点
    connected_targets = {edge["to"] for edge in graph.get("edges", [])}
    for node in graph.get("nodes", []):
        if node["id"] == start_nodes[0]["id"]:
            continue
        if node["id"] in connected_targets:
            continue
        if node["type"] == "end" or node["id"] not in edges_by_source:
            sg.add_edge(node["id"], END)

    return sg.compile(checkpointer=checkpointer)


def _build_state_schema(graph: dict[str, Any]) -> type:
    """从 graph 推断 state schema。

    首期用宽松 TypedDict，覆盖所有内置节点可能返回的 key，
    让节点间的中间字段（route / usage / results / status 等）能正常传递。
    """
    from typing import TypedDict

    class WorkflowState(TypedDict, total=False):
        input: dict
        output: dict
        route: str
        usage: dict
        results: list
        status: str
        error: str
        messages: list

    return WorkflowState
