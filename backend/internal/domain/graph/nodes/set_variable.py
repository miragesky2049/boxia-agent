"""SetVariable 节点（coze type=20 / VARIABLE_ASSIGN type=40）：写入全局变量。

config 约定：
- variableName: 变量名
- variableType: 可选，声明类型（string/number/boolean/object/array），用于值强制转换
- value: 字面量值（或通过 inputs.value 传入求值后的值）

A8：如果 graph 顶层 variables 池里声明了同名变量，按声明类型做强制转换。
"""

from __future__ import annotations

import logging

from internal.domain.canvas.node_type import NodeType
from internal.domain.canvas.variable_types import coerce as coerce_var
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class SetVariableNodeHandler(NodeHandler):
    type_name = NodeType.SET_VARIABLE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        var_name = str(ctx.config.get("variableName") or "")
        if not var_name:
            return NodeResult(outputs={"error": "set_variable 节点缺少 variableName"})

        value = ctx.inputs.get("value", ctx.config.get("value"))
        declared_type = str(ctx.config.get("variableType") or "")

        # A8：按声明类型强制转换
        if declared_type:
            coerced = coerce_var(value, declared_type)
            if coerced is None:
                logger.warning(
                    "变量 %s 类型 %s 转换失败，保留原值: value=%r",
                    var_name,
                    declared_type,
                    value,
                )
            else:
                value = coerced

        return NodeResult(
            outputs={var_name: value},
            globals={var_name: value},
        )


class VariableAssignNodeHandler(SetVariableNodeHandler):
    """VARIABLE_ASSIGN (type=40) 与 SET_VARIABLE 行为一致。"""

    type_name = NodeType.VARIABLE_ASSIGN.value


register_node_handler(SetVariableNodeHandler())
register_node_handler(VariableAssignNodeHandler())
