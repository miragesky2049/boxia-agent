"""Canvas IR：内部唯一的工作流图表示。

convert 阶段把 coze 画布 JSON 翻译成这套强类型模型；
Compiler 阶段只依赖这套模型，不直接接触原始 JSON。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from internal.domain.canvas.expression import Expr
from internal.domain.canvas.node_type import NodeType


@dataclass(frozen=True)
class PortSpec:
    """节点输出端口定义。对应 coze VariableMetaDTO。"""

    name: str
    type: str  # string / integer / float / boolean / object / list / image
    description: str = ""
    required: bool = False


@dataclass(frozen=True)
class NodeMeta:
    """节点元信息：运行时只需 title/description，position 仅用于观测。"""

    title: str = ""
    description: str = ""
    icon: str = ""
    position: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class ErrorPolicy:
    """节点错误处理策略。对应 coze settingOnError。

    processType:
      - 0: 中断整个工作流
      - 1: 跳过当前节点，继续往下（dataOnErr 作为输出）
    retryTimes: 节点级重试次数
    timeoutMs: 节点超时毫秒
    """

    process_type: int = 0
    retry_times: int = 0
    timeout_ms: int = 180_000
    data_on_err: str = ""


@dataclass(frozen=True)
class CanvasNode:
    """画布节点 IR。

    inputs: {param_name: Expr}，已从 coze inputs.inputParameters / llmParam 等扁平化为统一字典。
    config: 节点特定配置（model_id / temperature / url / method 等），未经表达式求值。
    subgraph: loop / batch / subworkflow 内嵌子图，递归处理。
    """

    id: str
    type: NodeType
    inputs: dict[str, Expr] = field(default_factory=dict)
    outputs: list[PortSpec] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    meta: NodeMeta = field(default_factory=NodeMeta)
    on_error: ErrorPolicy | None = None
    subgraph: CanvasGraph | None = None


@dataclass(frozen=True)
class CanvasEdge:
    """画布边。source_port 非空时对应 if/selector 的出口。"""

    source: str
    target: str
    source_port: str | None = None


@dataclass(frozen=True)
class CanvasGraph:
    """画布图 IR。"""

    nodes: list[CanvasNode]
    edges: list[CanvasEdge]
    # 顶层版本号，对应 coze versions.loop（用于兼容不同 loop 协议版本）
    versions: dict[str, str] = field(default_factory=dict)

    @property
    def start_node(self) -> CanvasNode:
        for node in self.nodes:
            if node.type == NodeType.START:
                return node
        raise ValueError("画布缺少 START 节点")

    def node_by_id(self, node_id: str) -> CanvasNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"画布不存在节点: {node_id}")

    def outgoing_edges(self, node_id: str) -> list[CanvasEdge]:
        return [edge for edge in self.edges if edge.source == node_id]
