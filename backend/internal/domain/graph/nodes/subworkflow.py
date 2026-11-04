"""Subworkflow 节点（coze type=9）：调用另一个 workflow。

config 约定（来自 coze inputDefs / workflowId）：
- workflowId: 要调用的子 workflow ID
- inputDefs: 输入参数定义
- spaceId: 空间 ID（多租户隔离用）

运行时通过 services.get("subgraph_loader") 获取子图加载器：
  loader(workflow_id) -> canvas_json dict
"""

from __future__ import annotations

import logging
from typing import Any

from internal.domain.canvas.convert import convert_canvas
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult, RuntimeEnv
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class SubworkflowNodeHandler(NodeHandler):
    type_name = NodeType.SUB_WORKFLOW.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        # 延迟导入避免循环依赖：compiler → nodes → subworkflow → compiler
        from internal.domain.graph.compiler import Compiler

        config = ctx.config
        workflow_id = str(config.get("workflowId") or "")

        if not workflow_id:
            return NodeResult(outputs={"error": "subworkflow 节点缺少 workflowId"})

        if not ctx.services.has("subgraph_loader"):
            return NodeResult(outputs={
                "input": f"[SUBWORKFLOW stub] workflowId={workflow_id}",
                "inputArr": [],
            })

        # 加载子图画布 JSON（loader 可能是 sync 或 async，统一 await 处理）
        loader = ctx.services.get("subgraph_loader")
        canvas_json = loader(workflow_id)
        if hasattr(canvas_json, "__await__"):
            canvas_json = await canvas_json
        if not canvas_json:
            return NodeResult(outputs={"error": f"子 workflow 不存在或无权访问: {workflow_id}"})

        # 转换为 IR 并编译
        sub_graph = convert_canvas(canvas_json)

        # 构造子图的运行时环境（复用父图的 env，但 run_id 用新的）
        import uuid
        sub_env = RuntimeEnv(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            run_id=uuid.uuid4(),
            thread_id=f"{ctx.env.thread_id}:sub:{workflow_id}",
            application_id=ctx.env.application_id,
        )

        # 编译子图（注意：子图用独立 compiler，不挂 checkpointer，避免父图 checkpoint 污染）
        sub_compiler = Compiler(services=ctx.services)
        compiled = sub_compiler.compile(sub_graph, sub_env, checkpointer=None)

        # 构造子图初始 state：把父图 inputs 映射为子图 input
        sub_input = dict(ctx.inputs)
        initial_state = {
            "input": sub_input,
            "node_outputs": {},
            "globals": {},
            "env": {
                "tenant_id": str(ctx.env.tenant_id),
                "user_id": str(ctx.env.user_id) if ctx.env.user_id else None,
                "run_id": str(sub_env.run_id),
                "thread_id": sub_env.thread_id,
            },
            "output": {},
            "errors": {},
        }

        # 执行子图
        result = await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": sub_env.thread_id}},
        )

        # 把子图输出作为当前节点输出
        output = result.get("output", {})
        return NodeResult(outputs=dict(output))


register_node_handler(SubworkflowNodeHandler())
