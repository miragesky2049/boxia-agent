"""v4 引擎：LangGraph 编译层 + 节点注册表。"""

from internal.engine.v4.compiler import compile_graph, infer_runtime_mode
from internal.engine.v4.events import NodeExecutionEvent, publish, subscribe
from internal.engine.v4.registry import NODE_REGISTRY, NodePlugin, get_node, list_node_types, register_node
from internal.engine.v4.runner import GraphRunner

# 导入内置节点以触发注册
import internal.engine.v4.nodes.builtin  # noqa: F401
import internal.engine.v4.events  # noqa: F401  (导入以触发内置订阅者注册)

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
