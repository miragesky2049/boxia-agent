"""SetVariable 节点（coze type=20 / VARIABLE_ASSIGN type=40）：写入全局变量。

config 约定：
- variableName: 变量名
- value: 字面量值（或通过 inputs.value 传入求值后的值）

运行时把值写入 state.globals[variableName]，后续节点可以通过 GlobalVar 引用。
"""

from __future__ import annotations

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class SetVariableNodeHandler(NodeHandler):
    type_name = NodeType.SET_VARIABLE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        var_name = str(ctx.config.get("variableName") or "")
        if not var_name:
            return NodeResult(outputs={"error": "set_variable 节点缺少 variableName"})

        value = ctx.inputs.get("value", ctx.config.get("value"))
        return NodeResult(
            outputs={var_name: value},
            globals={var_name: value},
        )


class VariableAssignNodeHandler(SetVariableNodeHandler):
    """VARIABLE_ASSIGN (type=40) 与 SET_VARIABLE 行为一致。"""

    type_name = NodeType.VARIABLE_ASSIGN.value


register_node_handler(SetVariableNodeHandler())
register_node_handler(VariableAssignNodeHandler())
