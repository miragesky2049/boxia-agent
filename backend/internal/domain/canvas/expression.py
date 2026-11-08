"""表达式系统：节点输入参数的求值抽象。

coze 画布的 ValueExpressionDTO 有两种：
- literal：字面量（字符串/数字/布尔/对象）
- ref：引用（上游节点输出 / 全局变量 / 环境变量）

本模块把它们翻译成强类型 Expr，运行时由 ExpressionEvaluator 统一求值。

扩展支持：
- TemplatedString：字符串模板，{{...}} 插值
- TemplateEvaluator：mini 表达式求值器（ast 白名单），支持 ref/字面量/比较/逻辑/内置函数
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


class Expr:
    """表达式基类。节点 handler 不直接接触原始画布 JSON，只通过 Expr 拿值。"""


@dataclass(frozen=True)
class LiteralValue(Expr):
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
class TemplatedString(Expr):
    """字符串模板：content 里的 {{...}} 会被求值插值。

    用于 prompt / HTTP body 等需要拼接上游输出的场景。
    例如："你好 {{start.output.USER_INPUT}}" → "你好 张三"
    """

    template: str


@dataclass(frozen=True)
class EvalContext:
    """求值上下文：节点输出表、全局变量、环境变量。

    node_outputs 在运行时由 Runtime 逐节点填充：{block_id: {field: value}}。
    variables 是应用变量作用域（默认值来自应用配置，运行期可被节点写入而更新）；
    system 是只读系统变量（USER_INPUT / USER_ID / RUN_ID 等）。
    """

    input: dict[str, Any]
    node_outputs: dict[str, dict[str, Any]]
    globals: dict[str, Any]
    env: dict[str, Any]
    variables: dict[str, Any] = field(default_factory=dict)
    system: dict[str, Any] = field(default_factory=dict)


# 内置函数白名单（不在此列表的 Python 内置函数不可调用）
_BUILTIN_FUNCS: dict[str, Callable[..., Any]] = {
    "len": lambda x: len(x) if x is not None else 0,
    "upper": lambda s: str(s).upper(),
    "lower": lambda s: str(s).lower(),
    "trim": lambda s: str(s).strip(),
    "json_parse": lambda s: json.loads(s) if s else None,
    "json_stringify": lambda v: json.dumps(v, ensure_ascii=False),
    "default": lambda v, d=None: v if v is not None else d,
}

# 模板插值正则：{{ ... }}（非贪婪）
_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")

# 合法的 Python 标识符（可用作 ast 的 Name）
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def rewrite_template_refs(
    expr: str,
    node_ids: list[str],
    name_keys: list[str] | None = None,
) -> tuple[str, dict[str, str]]:
    """把模板表达式里的节点引用重写成可被 ast 解析的安全别名。

    FlowGram/coze 的节点 ID 形如 `llm-mvxuv1f2-1`（含连字符），直接作为 Python
    表达式会报 `invalid decimal literal`。另外变量引用约定是
    `<nodeId>.output.<field>`，其中 `.output` 是固定关键字，实际取值应是
    `node_outputs[nodeId][field]`。

    这里把 `<nodeId>.output` 换成 `_ref_N`（丢掉固定关键字），使
    `llm-mvxuv1f2-1.output.output` → `_ref_0.output`；全局变量/入参名若含非法
    标识符字符，也做同样替换。

    Args:
        expr: 待解析的表达式文本（已去掉外层 {{ }}）。
        node_ids: 画布中可引用的节点 ID 列表（可含连字符）。
        name_keys: 全局变量 / 入参名等基名列表，可选。

    Returns:
        (重写后的表达式, {别名: 原始节点ID或变量名})。调用方用别名映射还原取值。
    """
    aliases: dict[str, str] = {}
    result = expr
    next_index = 0

    # 1) 节点引用：优先吃掉固定的 `.output` 关键字，再兜底裸节点 ID
    for node_id in sorted({n for n in node_ids if n}, key=lambda s: (-len(s), s)):
        alias = f"_ref_{next_index}"
        head = r"(?<![A-Za-z0-9_.\-])" + re.escape(node_id)
        with_output = re.compile(head + r"\.output(?![A-Za-z0-9_\-])")
        bare = re.compile(head + r"(?![A-Za-z0-9_\-])")
        changed = False
        if with_output.search(result):
            result = with_output.sub(alias, result)
            changed = True
        if bare.search(result):
            result = bare.sub(alias, result)
            changed = True
        if changed:
            aliases[alias] = node_id
            next_index += 1

    # 2) 全局变量 / 入参名：仅处理含非法标识符字符的基名
    for key in sorted(
        {k for k in (name_keys or []) if k and not _IDENTIFIER_RE.match(k)},
        key=lambda s: (-len(s), s),
    ):
        alias = f"_ref_{next_index}"
        pattern = re.compile(r"(?<![A-Za-z0-9_.\-])" + re.escape(key) + r"(?![A-Za-z0-9_\-])")
        if pattern.search(result):
            result = pattern.sub(alias, result)
            aliases[alias] = key
            next_index += 1

    return result, aliases


class TemplateEvaluator:
    """mini 表达式求值器：处理 {{...}} 插值和单个表达式求值。

    安全模型：用 ast 解析，白名单节点类型，不调用任意函数。
    支持：
    - 属性访问链：start.output.USER_INPUT
    - 字面量：'string' / "string" / 123 / true / false / null
    - 比较：== != > < >= <= in not in
    - 逻辑：and or not
    - 内置函数：len / upper / lower / trim / json_parse / json_stringify / default
    """

    def eval_template(self, template: str, ctx: EvalContext) -> str:
        """把 template 里的 {{...}} 替换成求值结果。混合文本场景。"""
        if not template or "{{" not in template:
            return template
        parts: list[str] = []
        last = 0
        for m in _TEMPLATE_RE.finditer(template):
            parts.append(template[last : m.start()])
            value = self.eval_expression(m.group(1), ctx)
            parts.append("" if value is None else str(value))
            last = m.end()
        parts.append(template[last:])
        return "".join(parts)

    def eval_expression(self, expr: str, ctx: EvalContext) -> Any:
        """求值单个表达式字符串。整个字段就是一个 {{...}} 时返回原始类型。"""
        expr = expr.strip()
        if not expr:
            return None
        source, aliases = rewrite_template_refs(
            expr,
            node_ids=list(ctx.node_outputs),
            name_keys=[*ctx.variables, *ctx.system, *ctx.globals, *ctx.input],
        )
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError:
            # 语法错误原样返回，让 handler 拿到原始字符串
            return expr
        try:
            return self._eval_node(tree.body, ctx, aliases)
        except (_ExpressionError, KeyError, AttributeError):
            return None

    def _eval_node(self, node: ast.AST, ctx: EvalContext, aliases: dict[str, str]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, ctx, aliases)
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value, ctx, aliases)
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(node.attr)
            return getattr(obj, node.attr, None)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._eval_node(node.left, ctx, aliases)
            right = self._eval_node(node.right, ctx, aliases)
            if isinstance(left, str) or isinstance(right, str):
                return str(left or "") + str(right or "")
            return (left or 0) + (right or 0)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, ctx, aliases)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._eval_node(comparator, ctx, aliases)
                if not _compare(left, op, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v, ctx, aliases) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._eval_node(node.operand, ctx, aliases)
        if isinstance(node, ast.Call):
            func = self._eval_node(node.func, ctx, aliases)
            args = [self._eval_node(a, ctx, aliases) for a in node.args]
            if callable(func):
                return func(*args)
            raise _ExpressionError(f"不可调用: {ast.dump(node.func)}")
        raise _ExpressionError(f"不支持的表达式节点: {ast.dump(node)}")

    def _resolve_name(self, name: str, ctx: EvalContext, aliases: dict[str, str]) -> Any:
        # 命名空间：{{variables.xxx}} / {{system.USER_INPUT}}
        if name == "variables":
            # 节点对应用变量的写入落在 globals，globals 覆盖默认值以体现运行期更新
            return {**ctx.variables, **ctx.globals}
        if name == "system":
            return ctx.system

        # 别名映射：还原成原始节点 ID / 变量名后按输出表查找
        if name in aliases:
            key = aliases[name]
            if key in ctx.node_outputs:
                return ctx.node_outputs[key]
            if key in ctx.variables:
                return ctx.variables[key]
            if key in ctx.system:
                return ctx.system[key]
            if key in ctx.globals:
                return ctx.globals[key]
            if key in ctx.input:
                return ctx.input[key]
            return None
        if name in _BUILTIN_FUNCS:
            return _BUILTIN_FUNCS[name]
        if name in ("true", "True"):
            return True
        if name in ("false", "False"):
            return False
        if name in ("null", "None"):
            return None
        # 作用域顺序对齐 coze：node_outputs → variables → system → globals → input
        if name in ctx.node_outputs:
            return ctx.node_outputs[name]
        if name in ctx.variables:
            return ctx.variables[name]
        if name in ctx.system:
            return ctx.system[name]
        if name in ctx.globals:
            return ctx.globals[name]
        if name in ctx.input:
            return ctx.input[name]
        return None


class _ExpressionError(Exception):
    """表达式求值失败，由外层捕获后返回 None。"""


def _compare(left: Any, op: ast.cmpop, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return _safe_lt(left, right)
    if isinstance(op, ast.LtE):
        return _safe_lt(left, right) or left == right
    if isinstance(op, ast.Gt):
        return not _safe_lt(left, right) and left != right
    if isinstance(op, ast.GtE):
        return not _safe_lt(left, right)
    if isinstance(op, ast.In):
        try:
            return left in right
        except TypeError:
            return False
    if isinstance(op, ast.NotIn):
        try:
            return left not in right
        except TypeError:
            return True
    return False


def _safe_lt(left: Any, right: Any) -> bool:
    try:
        return left < right
    except TypeError:
        return False


class ExpressionEvaluator:
    """把 Expr 求值成具体值。节点 handler 在 run() 前批量调用。

    注意：本类的 eval() 是普通方法，不是 Python 内建 eval()。
    输入只有 LiteralValue/Ref/GlobalVar/EnvVar/TemplatedString 等封闭类型，不执行任意代码，
    安全等价于 dict 查表。
    """

    def __init__(self) -> None:
        self._template = TemplateEvaluator()

    def eval(self, expr: Expr, ctx: EvalContext) -> Any:
        if isinstance(expr, LiteralValue):
            return expr.value
        if isinstance(expr, Ref):
            node_out = ctx.node_outputs.get(expr.block_id, {})
            return node_out.get(expr.name)
        if isinstance(expr, GlobalVar):
            return ctx.globals.get(expr.name)
        if isinstance(expr, EnvVar):
            return ctx.env.get(expr.name)
        if isinstance(expr, TemplatedString):
            return self._template.eval_template(expr.template, ctx)
        raise TypeError(f"未知表达式类型: {type(expr).__name__}")

    def eval_dict(
        self,
        mapping: dict[str, Expr],
        ctx: EvalContext,
    ) -> dict[str, Any]:
        """批量求值：{name: Expr} → {name: value}。"""
        return {name: self.eval(expr, ctx) for name, expr in mapping.items()}

    def resolve_config(self, value: Any, ctx: EvalContext) -> Any:
        """对 config 字段求值：Expr 求值，其他类型原样返回。

        handler 用法：prompt = ctx.evaluator.resolve_config(config.get("prompt"), ctx.eval_context)
        """
        if isinstance(value, Expr):
            return self.eval(value, ctx)
        if isinstance(value, list):
            return [self.resolve_config(item, ctx) for item in value]
        if isinstance(value, dict):
            return {k: self.resolve_config(v, ctx) for k, v in value.items()}
        return value

    @property
    def template(self) -> TemplateEvaluator:
        """暴露模板求值器，供 handler 对 config 里的 prompt/body 等做插值。"""
        return self._template
