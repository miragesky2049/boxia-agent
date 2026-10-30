"""Compiler：CanvasGraph IR → langgraph CompiledStateGraph。

核心职责：
1. 为每个 CanvasNode 生成一个 async node function（闭包捕获 inputs/config/handler）
2. 处理边：普通边 add_edge；IF 节点用 conditional_edges 按 route 路由
3. START 是 entry point；END 节点的输出写入 state.output
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Annotated
from uuid import UUID

from langgraph.graph import END, StateGraph

from internal.domain.canvas.expression import EvalContext, ExpressionEvaluator
from internal.domain.canvas.model import CanvasGraph, CanvasNode
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes import get_node_handler
from internal.domain.graph.state import WorkflowState, merge_dict


def _build_state_schema() -> type:
    """带 reducer 的 state schema：node_outputs / globals 用 merge_dict 合并。"""

    class State(WorkflowState, total=False):
        node_outputs: Annotated[dict[str, dict[str, Any]], merge_dict]
        globals: Annotated[dict[str, Any], merge_dict]
        errors: Annotated[dict[str, str], merge_dict]

    return State

logger = logging.getLogger(__name__)


class Compiler:
    """把 CanvasGraph 编译成 langgraph 可执行图。"""

    def __init__(self, services: ServiceRegistry | None = None):
        self._services = services or ServiceRegistry()
        self._evaluator = ExpressionEvaluator()

    def compile(
        self,
        graph: CanvasGraph,
        env: RuntimeEnv,
        checkpointer: Any = None,
    ) -> Any:
        """编译 CanvasGraph。

        Args:
            graph: 画布 IR
            env: 运行时环境（tenant_id / user_id / run_id / thread_id）
            checkpointer: langgraph checkpointer（AsyncPostgresSaver）

        Returns:
            langgraph CompiledStateGraph
        """
        state_schema = _build_state_schema()
        sg = StateGraph(state_schema)

        # 注册每个节点
        node_fns: dict[str, Callable[[dict], Awaitable[dict]]] = {}
        for canvas_node in graph.nodes:
            handler = get_node_handler(canvas_node.type)
            node_fn = self._build_node_fn(canvas_node, handler, env)
            node_fns[canvas_node.id] = node_fn
            sg.add_node(canvas_node.id, node_fn)

        # 找 START 节点
        start_node = graph.start_node
        sg.set_entry_point(start_node.id)

        # 按 source 分组出边
        edges_by_source: dict[str, list] = {}
        for edge in graph.edges:
            edges_by_source.setdefault(edge.source, []).append(edge)

        # 注册边
        for source_id, out_edges in edges_by_source.items():
            source_node = graph.node_by_id(source_id)
            # IF 节点：conditional_edges，按 route 路由
            if source_node.type == NodeType.IF:
                self._add_conditional_edges(sg, source_id, out_edges)
            else:
                for edge in out_edges:
                    target = edge.target if edge.target else END
                    sg.add_edge(source_id, target)

        # 没有出边的节点 → END
        connected_targets = {edge.target for edge in graph.edges}
        for node in graph.nodes:
            if node.id == start_node.id:
                continue
            if node.id not in connected_targets and node.id not in edges_by_source:
                sg.add_edge(node.id, END)

        return sg.compile(checkpointer=checkpointer)

    def _build_node_fn(
        self,
        canvas_node: CanvasNode,
        handler: NodeHandler,
        env: RuntimeEnv,
    ) -> Callable[[dict], Awaitable[dict]]:
        """为单个节点生成 langgraph node function。"""
        node_id = canvas_node.id
        inputs_expr = canvas_node.inputs
        config = canvas_node.config
        node_type = canvas_node.type

        async def node_fn(state: dict) -> dict:
            # 构造求值上下文
            ctx = EvalContext(
                input=state.get("input", {}),
                node_outputs=state.get("node_outputs", {}),
                globals=state.get("globals", {}),
                env=state.get("env", {}),
            )

            # 批量求值 inputs
            evaluated_inputs = self._evaluator.eval_dict(inputs_expr, ctx)

            # START 节点特殊处理：inputs 为空时，把 state.input 直接作为 inputs
            # 这样 START handler 能把整个入参写入 node_outputs
            if node_type == NodeType.START and not evaluated_inputs:
                evaluated_inputs = dict(state.get("input", {}))

            # 构造 NodeContext
            node_ctx = NodeContext(
                node_id=node_id,
                node_type=node_type.value,
                inputs=evaluated_inputs,
                config=config,
                env=env,
                services=self._services,
                subgraph=canvas_node.subgraph,
            )

            # 调 handler
            result = await handler.run(node_ctx)

            # 构造 state 更新
            update: dict[str, Any] = {
                "node_outputs": {node_id: {**result.outputs, "usage": result.usage}},
            }

            # SetVariable / VariableAssign 节点：把 globals 写入全局变量池
            if result.globals:
                update["globals"] = dict(result.globals)

            # END 节点：把 outputs 写到 state.output
            if node_type == NodeType.END:
                update["output"] = result.outputs

            return update

        return node_fn

    def _add_conditional_edges(
        self,
        sg: StateGraph,
        source_id: str,
        out_edges: list,
    ) -> None:
        """IF 节点：按 route（"true"/"false"）路由到目标节点。"""
        # 建立 route → target 映射
        route_map: dict[str, str] = {}
        for edge in out_edges:
            port = edge.source_port or "true"
            route_map[port] = edge.target

        def router(state: dict) -> str:
            node_out = state.get("node_outputs", {}).get(source_id, {})
            route = node_out.get("route", "false")
            return route_map.get(route, route_map.get("false", END))

        sg.add_conditional_edges(source_id, router, route_map)
