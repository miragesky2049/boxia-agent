"""节点 handler 注册表。

每个节点类型一个文件，通过 register_node_handler 注册。
Compiler 根据 CanvasNode.type 查对应 handler。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeHandler

# node_type 值 → handler 实例
_HANDLERS: dict[str, NodeHandler] = {}


def register_node_handler(handler: NodeHandler) -> None:
    """注册节点 handler。"""
    if not handler.type_name:
        raise ValueError(f"handler 未设置 type_name: {type(handler).__name__}")
    _HANDLERS[handler.type_name] = handler


def get_node_handler(node_type: NodeType | str) -> NodeHandler:
    """按节点类型取 handler。"""
    key = node_type.value if isinstance(node_type, NodeType) else str(node_type)
    if key not in _HANDLERS:
        raise KeyError(f"未注册的节点类型 handler: {key}")
    return _HANDLERS[key]


def list_registered_types() -> list[str]:
    return sorted(_HANDLERS.keys())


# 导入各节点模块以触发注册
from internal.domain.graph.nodes import (  # noqa: E402,F401
    start,
    end,
    llm,
    if_else,
    http,
    subworkflow,
    loop,
    break_node,
    continue_node,
    variable_merge,
    dataset,
    dataset_write,
    code,
    batch,
    set_variable,
    text_processor,
    json_tools,
    conversation_nodes,
    human_task,
    agent_loop,
    api_plugin,
    comment,
)
