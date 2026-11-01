"""T7: IF 节点结构化 case（left/operator/right）单测。

验证：
- 结构化 case 自动拼接成表达式并求值
- 各操作符（eq/ne/gt/gte/lt/lte/contains/not_contains/is_empty/is_not_empty）
- 已有 expression 字段时直接使用，不重复拼接
- 多 case 时第一个为真的 case_id 作为 route
- 全部为假时走 else_port
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.canvas.expression import EvalContext, ExpressionEvaluator
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.if_else import IfElseNodeHandler


def _make_ctx(
    config: dict,
    *,
    start_output: dict | None = None,
) -> NodeContext:
    """构造 IF 节点测试上下文。

    START 节点输出是平铺的 {字段: 值}，表达式 `{{start.output.<key>}}` 中的
    `.output` 是固定关键字，实际取 node_outputs["start"]["<key>"]。
    """
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )
    node_outputs = {
        "start": dict(start_output or {}),
    }
    eval_ctx = EvalContext(
        input=start_output or {},
        node_outputs=node_outputs,
        globals={},
        env={},
    )
    return NodeContext(
        node_id="if_1",
        node_type=NodeType.IF.value,
        inputs={},
        config=config,
        env=env,
        services=ServiceRegistry(),
        eval_context=eval_ctx,
        evaluator=ExpressionEvaluator(),
    )


def test_structured_case_eq_matches() -> None:
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "age_adult",
            "left": "{{start.output.age}}",
            "operator": "eq",
            "right": "18",
        }]},
        start_output={"age": 18},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "age_adult"


def test_structured_case_ne_falls_to_else() -> None:
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "is_child",
            "left": "{{start.output.age}}",
            "operator": "ne",
            "right": "18",
        }],
        "else_port": "else"},
        start_output={"age": 18},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "else"


def test_structured_case_gt() -> None:
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "gt_18",
            "left": "{{start.output.age}}",
            "operator": "gt",
            "right": "18",
        }]},
        start_output={"age": 20},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "gt_18"


def test_structured_case_contains_swaps_sides() -> None:
    # coze contains 语义：left 包含 right；Python `in` 是 needle in haystack
    # 拼接后应该是 `'bar' in ('foo bar baz')`
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "has_bar",
            "left": "{{start.output.text}}",
            "operator": "contains",
            "right": "bar",
        }]},
        start_output={"text": "foo bar baz"},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "has_bar"


def test_structured_case_is_empty() -> None:
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "empty",
            "left": "{{start.output.note}}",
            "operator": "is_empty",
        }]},
        start_output={"note": ""},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "empty"


def test_structured_case_is_not_empty() -> None:
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "non_empty",
            "left": "{{start.output.note}}",
            "operator": "is_not_empty",
        }]},
        start_output={"note": "hello"},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "non_empty"


def test_existing_expression_field_is_used_directly() -> None:
    # 已经有 expression 字段时，不应该再走 left/operator/right 拼接
    ctx = _make_ctx(
        {"cases": [{
            "case_id": "custom",
            "expression": "{{start.output.age}} >= 60",
        }]},
        start_output={"age": 65},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "custom"


def test_multi_case_first_truthy_wins() -> None:
    ctx = _make_ctx(
        {"cases": [
            {
                "case_id": "child",
                "left": "{{start.output.age}}",
                "operator": "lt",
                "right": "18",
            },
            {
                "case_id": "adult",
                "left": "{{start.output.age}}",
                "operator": "gte",
                "right": "18",
            },
        ],
        "else_port": "else"},
        start_output={"age": 30},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    # 第一个 case (lt 18) 为假，第二个 (gte 18) 为真
    assert result.route == "adult"


def test_all_cases_false_falls_to_else_port() -> None:
    ctx = _make_ctx(
        {"cases": [
            {
                "case_id": "child",
                "left": "{{start.output.age}}",
                "operator": "lt",
                "right": "18",
            },
            {
                "case_id": "senior",
                "left": "{{start.output.age}}",
                "operator": "gte",
                "right": "65",
            },
        ],
        "else_port": "middle"},
        start_output={"age": 30},
    )
    result = asyncio.run(IfElseNodeHandler().run(ctx))
    assert result.route == "middle"
