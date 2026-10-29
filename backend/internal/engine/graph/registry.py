"""节点注册表：节点类型插件化，加新节点不改画布核心。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class PortSpec:
    """节点端口定义。"""

    name: str
    type: str  # string / number / object / array / any
    description: str = ""


@dataclass(frozen=True)
class NodePlugin:
    """节点插件包定义。"""

    type: str
    version: str
    config_schema: dict[str, Any]
    build: Callable[[dict[str, Any]], Callable]
    input_ports: list[PortSpec] = field(default_factory=list)
    output_ports: list[PortSpec] = field(default_factory=list)
    migrate: Callable[[dict[str, Any], str], dict[str, Any]] | None = None


NODE_REGISTRY: dict[str, NodePlugin] = {}


def register_node(plugin: NodePlugin) -> None:
    """注册节点类型。"""
    NODE_REGISTRY[plugin.type] = plugin


def get_node(node_type: str) -> NodePlugin:
    """获取节点插件，未注册抛错。"""
    if node_type not in NODE_REGISTRY:
        raise ValueError(f"未注册的节点类型: {node_type}")
    return NODE_REGISTRY[node_type]


def list_node_types() -> list[str]:
    """列出所有已注册节点类型。"""
    return sorted(NODE_REGISTRY.keys())
