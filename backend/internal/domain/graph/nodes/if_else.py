"""IF 条件分支节点（coze type=8）。

coze 的 IF 节点 config 里有 cases 结构：
- cases: [{case_id, expression}] — 每个 case 一个布尔表达式
- else_port: 字符串（默认 "false"），所有 case 都不匹配时走这个出口

本 handler 负责计算 route（出口端口名），实际路由由 Compiler 的 conditional_edges 处理。

兼容旧版：config 没有 cases 时，走 inputs.condition 单条件布尔求值。
"""

from __future__ import annotations

from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler


class IfElseNodeHandler(NodeHandler):
    type_name = NodeType.IF.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        cases = ctx.config.get("cases")
        if isinstance(cases, list) and cases:
            return self._eval_multi_cases(ctx, cases)
        return self._eval_single_condition(ctx)

    def _eval_multi_cases(self, ctx: NodeContext, cases: list[Any]) -> NodeResult:
        """多 case：逐个求值 expression，第一个为真的 case_id 作为 route。"""
        else_port = str(ctx.config.get("else_port") or "false")
        outputs: dict[str, Any] = {}
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or case.get("id") or "")
            expr = case.get("expression") or case.get("condition")
            if expr is None:
                continue
            # 用 evaluator 求值：Expr 求表达式，其他类型直接判断
            if ctx.evaluator is not None and ctx.eval_context is not None:
                value = ctx.evaluator.resolve_config(expr, ctx.eval_context)
            else:
                value = expr
            outputs[case_id] = value
            if _is_truthy(value):
                return NodeResult(outputs=outputs, route=case_id)
        return NodeResult(outputs=outputs, route=else_port)

    def _eval_single_condition(self, ctx: NodeContext) -> NodeResult:
        """兼容旧版：inputs.condition 单条件布尔求值。"""
        condition_value = ctx.inputs.get("condition")
        matched = bool(condition_value)
        return NodeResult(
            outputs={"condition": condition_value},
            route="true" if matched else "false",
        )


def _is_truthy(value: Any) -> bool:
    """表达式求值结果的真值判断：None/空串/0/False 都视为假。"""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "null", "none")
    return bool(value)


register_node_handler(IfElseNodeHandler())
