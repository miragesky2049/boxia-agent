"""引擎：LangGraph 编译层 + 节点注册表。"""

from internal.engine.graph.compiler import compile_graph, infer_runtime_mode
from internal.engine.graph.events import NodeExecutionEvent, publish, subscribe
from internal.engine.graph.registry import NODE_REGISTRY, NodePlugin, get_node, list_node_types, register_node
from internal.engine.graph.runner import GraphRunner

# 导入内置节点以触发注册
import internal.engine.graph.nodes.builtin  # noqa: F401
import internal.engine.graph.events  # noqa: F401  (导入以触发内置订阅者注册)

__all__ = [
    "compile_graph",
    "infer_runtime_mode",
    "NODE_REGISTRY",
    "NodePlugin",
    "get_node",
    "list_node_types",
    "register_node",
    "GraphRunner",
    "NodeExecutionEvent",
    "publish",
    "subscribe",
]
