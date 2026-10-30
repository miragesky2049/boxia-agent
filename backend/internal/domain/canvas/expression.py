"""表达式系统：节点输入参数的求值抽象。

coze 画布的 ValueExpressionDTO 有两种：
- literal：字面量（字符串/数字/布尔/对象）
- ref：引用（上游节点输出 / 全局变量 / 环境变量）

本模块把它们翻译成强类型 Expr，运行时由 ExpressionEvaluator 统一求值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class Expr:
    """表达式基类。节点 handler 不直接接触原始画布 JSON，只通过 Expr 拿值。"""


@dataclass(frozen=True)
class Literal(Expr):
    """字面量：字符串、数字、布尔、对象。"""

    value: Any


@dataclass(frozen=True)
class Ref(Expr):
    """引用上游节点输出。

    block_id 对应画布中的节点 id；name 是该节点 outputs 里定义的字段名。
    """

    block_id: str
    name: str


@dataclass(frozen=True)
class GlobalVar(Expr):
    """引用工作流全局变量（VariableAssign / SetVariable 节点写入）。"""

    name: str


@dataclass(frozen=True)
class EnvVar(Expr):
    """引用运行时环境变量（tenant_id / user_id / run_id / thread_id）。"""

    name: Literal["tenant_id", "user_id", "run_id", "thread_id"]


@dataclass(frozen=True)
class EvalContext:
    """求值上下文：节点输出表、全局变量、环境变量。

    node_outputs 在运行时由 Runtime 逐节点填充：{block_id: {field: value}}。
    """

    input: dict[str, Any]
    node_outputs: dict[str, dict[str, Any]]
    globals: dict[str, Any]
    env: dict[str, Any]


class ExpressionEvaluator:
    """把 Expr 求值成具体值。节点 handler 在 run() 前批量调用。

    注意：本类的 eval() 是普通方法，不是 Python 内建 eval()。
    输入只有 Literal/Ref/GlobalVar/EnvVar 四种封闭类型，不执行任意代码，
    安全等价于 dict 查表。
    """

    def eval(self, expr: Expr, ctx: EvalContext) -> Any:
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Ref):
            node_out = ctx.node_outputs.get(expr.block_id, {})
            return node_out.get(expr.name)
        if isinstance(expr, GlobalVar):
            return ctx.globals.get(expr.name)
        if isinstance(expr, EnvVar):
            return ctx.env.get(expr.name)
        raise TypeError(f"未知表达式类型: {type(expr).__name__}")

    def eval_dict(
        self,
        mapping: dict[str, Expr],
        ctx: EvalContext,
    ) -> dict[str, Any]:
        """批量求值：{name: Expr} → {name: value}。"""
        return {name: self.eval(expr, ctx) for name, expr in mapping.items()}
