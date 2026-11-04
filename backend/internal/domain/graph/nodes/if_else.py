"""IF 条件分支节点（coze type=8）。

coze 的 IF 节点 config 里有 cases 结构：
- cases: [{case_id, expression}] — 每个 case 一个布尔表达式
- else_port: 字符串（默认 "false"），所有 case 都不匹配时走这个出口

本 handler 负责计算 route（出口端口名），实际路由由 Compiler 的 conditional_edges 处理。

兼容旧版：config 没有 cases 时，走 inputs.condition 单条件布尔求值。

T7 扩展：支持结构化 case `{case_id, left, operator, right}`，handler 自动把它拼成
expression 字符串（左值引用 + 操作符 + 右值字面量），再走统一求值路径。
"""

from __future__ import annotations

import json
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

# 可视化编辑器支持的操作符 → 表达式中使用的 Python 比较运算符
_OPERATOR_MAP: dict[str, str] = {
    "eq": "==",
    "ne": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    # contains / not_contains：coze 语义是 left 包含 right；Python `in` 是 needle in haystack，
    # 所以左右要对调。
    "contains": "in",
    "not_contains": "not in",
    "is_empty": "is_empty",
    "is_not_empty": "is_not_empty",
}


def _normalize_case_expression(case: dict[str, Any]) -> Any:
    """把结构化 case {left, operator, right} 转成可求值的 expression 字符串。

    - 已经有 expression / condition 字段时直接返回
    - 否则按 left/operator/right 拼：
        * left 是引用（如 {{node.output.field}}），直接当表达式
        * right 是字面量：数字 → 直接写；true/false → 布尔；其他 → 加引号
        * contains/not_contains 左右对调：`right in left`
        * is_empty/is_not_empty 退化成对 left 本身的真值判断
    """
    if "expression" in case or "condition" in case:
        return case.get("expression") or case.get("condition")

    left = case.get("left")
    operator = str(case.get("operator") or "").strip()
    right = case.get("right")

    if left is None or not operator:
        return None

    op_py = _OPERATOR_MAP.get(operator)
    if op_py is None:
        return None

    left_expr = _to_expression_value(left)

    if op_py == "is_empty":
        # not (left)：None / 空串 / 0 / False 都视为空
        return f"not ({left_expr})"
    if op_py == "is_not_empty":
        # 不依赖 bool() 内置函数，用双 not 取真值（ast 白名单支持 UnaryOp Not）
        return f"not not ({left_expr})"

    right_expr = _to_expression_value(right)

    if op_py in ("in", "not in"):
        # coze contains 语义：left 包含 right → Python `right in left`
        return f"({right_expr}) {op_py} ({left_expr})"

    return f"({left_expr}) {op_py} ({right_expr})"


def _to_expression_value(raw: Any) -> str:
    """把 case 字段值转成表达式片段字符串。

    - 已经是 {{...}} 形式的引用 → 剥掉 {{ }}（evaluator 直接吃 node.output.field 这种名字）
    - 数字 / bool → 字面量
    - 其他 → json.dumps 成带双引号字符串字面量
    """
    if raw is None:
        return "None"
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (int, float)):
        return repr(raw)

    text = str(raw).strip()
    if text.startswith("{{") and text.endswith("}}"):
        # {{node_id.output.field}} → node_id.output.field
        inner = text[2:-2].strip()
        return inner if inner else "None"
    # 去掉外层引号（用户手动写的 "abc"）
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        return text
    # 尝试解析数字 / bool
    try:
        return str(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        pass
    # 字符串字面量：统一用 json.dumps 加双引号，避免 shlex.quote 对单词不加引号
    return json.dumps(text, ensure_ascii=False)


class IfElseNodeHandler(NodeHandler):
    type_name = NodeType.IF.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        cases = ctx.config.get("cases")
        if isinstance(cases, list) and cases:
            return self._eval_multi_cases(ctx, cases)
        return self._eval_single_condition(ctx)

    def _eval_multi_cases(self, ctx: NodeContext, cases: list[Any]) -> NodeResult:
        """多 case：逐个求值 expression，第一个为真的 case_id 作为 route。"""
        # 否则出口端口名默认 "else"（与前端动态端口渲染一致）；旧图兼容 "false"
        else_port = str(ctx.config.get("else_port") or "else")
        outputs: dict[str, Any] = {}
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or case.get("id") or "")
            expr = _normalize_case_expression(case)
            if expr is None:
                continue
            # 新建节点的默认「如果」只有 case_id、没有配置左值：
            # 若继续求值会得到 ("" == "") 恒真，导致永远走第一个分支
            if not _has_case_operand(case):
                continue
            # 用 evaluator 求值：拼接出的是字符串表达式（如 "(start.output.age) != (18)"），
            # 走 TemplateEvaluator.eval_expression 解析 ast 并求值；若已是 Expr 对象则走 resolve_config。
            # 用户手写 expression 可能带 {{...}} 模板插值，先 eval_template 剥掉再 eval_expression。
            if ctx.evaluator is not None and ctx.eval_context is not None:
                if isinstance(expr, str):
                    raw = expr
                    if "{{" in raw:
                        raw = ctx.evaluator.template.eval_template(raw, ctx.eval_context)
                    value = ctx.evaluator.template.eval_expression(raw, ctx.eval_context)
                else:
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


def _has_case_operand(case: dict[str, Any]) -> bool:
    """判断 case 是否已配置有效的求值输入。

    - 手写 expression / condition 且非空白 → 有效
    - 结构化 case 的 left 非空白 → 有效（is_empty / is_not_empty 也依赖 left）
    - 其余（只有 case_id 的空模板）→ 无效，应跳过
    """
    if "expression" in case or "condition" in case:
        raw = case.get("expression") or case.get("condition")
        return bool(str(raw).strip()) if raw is not None else False
    left = case.get("left")
    if left is None:
        return False
    if isinstance(left, str):
        return bool(left.strip())
    return True


def _is_truthy(value: Any) -> bool:
    """表达式求值结果的真值判断：None/空串/0/False 都视为假。"""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "null", "none")
    return bool(value)


register_node_handler(IfElseNodeHandler())
