"""节点 handler 抽象基类与上下文。

节点 handler 是纯业务逻辑，不直接 import langgraph / SQLAlchemy / FastAPI。
所有依赖通过 NodeContext.services 注入，可测试性强。

DDD 分层约定：
- NodeContext 是值对象，只持有数据，不含业务行为
- 表达式求值是领域服务能力，由 ExpressionEvaluator（domain/canvas）提供
- handler 通过 ctx.evaluator 调用求值，不在 ctx 上写业务方法
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from internal.domain.canvas.expression import EvalContext, ExpressionEvaluator
from internal.domain.canvas.model import CanvasGraph


@dataclass(frozen=True)
class RuntimeEnv:
    """运行时环境变量：由 Runtime 在 invoke 前填充。"""

    tenant_id: UUID
    user_id: UUID | None
    run_id: UUID
    thread_id: str
    application_id: UUID


@dataclass(frozen=True)
class NodeContext:
    """单个节点执行时的上下文（值对象）。

    inputs: 已求值的入参（{name: value}），由 Compiler 在调 handler 前批量求值。
    config: 节点特定配置（model_id / temperature / url 等），可能含 Expr（TemplatedString/Ref）。
    env: 运行时环境（tenant_id / user_id / run_id / thread_id）。
    services: 服务注册表（llm / retrieval / tool_gateway / sandbox 等）。
    subgraph: Loop/Batch 等内嵌子图节点时携带的循环体 IR，普通节点为 None。
    eval_context: 求值上下文（含 node_outputs/globals/env），由 Compiler 逐节点构造。
    evaluator: 表达式求值领域服务，handler 用它对 config 里的动态字段求值。
    """

    node_id: str
    node_type: str
    inputs: dict[str, Any]
    config: dict[str, Any]
    env: RuntimeEnv
    services: "ServiceRegistry"
    subgraph: CanvasGraph | None = None
    eval_context: EvalContext | None = None
    evaluator: ExpressionEvaluator | None = None


@dataclass(frozen=True)
class NodeResult:
    """节点执行结果。

    outputs: 本节点产出的字段，会被写入 state.node_outputs[node_id]。
    route: 仅 if/selector 节点用，标识出口端口名。
    usage: LLM 节点的 token 用量，用于计费。
    globals: 需要写入 state.globals 的键值对（SetVariable / VariableAssign 用）。
    """

    outputs: dict[str, Any] = field(default_factory=dict)
    route: str | None = None
    usage: dict[str, int] | None = None
    globals: dict[str, Any] = field(default_factory=dict)


class NodeHandler(ABC):
    """节点 handler 基类。每个具体节点类型实现一个子类。"""

    type_name: str = ""

    @abstractmethod
    async def run(self, ctx: NodeContext) -> NodeResult:
        """执行节点逻辑。抛异常时由 Runtime 按 ErrorPolicy 处理。"""


class ServiceRegistry:
    """服务注册表：节点通过 ctx.services 拿依赖，不直接 import 基础设施。

    用 dict 持有具体服务实例，避免在 domain 层引用 engine/infrastructure 类型。
    """

    def __init__(self, services: dict[str, Any] | None = None):
        self._services: dict[str, Any] = dict(services or {})

    def get(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"服务未注册: {name}")
        return self._services[name]

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def has(self, name: str) -> bool:
        return name in self._services
