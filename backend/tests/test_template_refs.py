"""模板引用求值：支持含连字符的节点 ID + `.output` 关键字语义。

FlowGram/coze 的节点 ID 形如 `llm-mvxuv1f2-1`，直接当作 Python 表达式会报
`invalid decimal literal`；同时引用约定 `<nodeId>.output.<field>` 里的 `.output`
是固定关键字，取值应落到 `node_outputs[nodeId][field]`。
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.canvas.expression import EvalContext, ExpressionEvaluator
from internal.domain.canvas.node_type import NodeType
from internal.domain.canvas.validate import validate_raw_graph
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.end import EndNodeHandler
from internal.domain.graph.nodes.llm import LLMNodeHandler


def _ctx_with_outputs(node_outputs: dict[str, dict]) -> EvalContext:
    return EvalContext(
        input={"input": "张师傅"},
        node_outputs=node_outputs,
        globals={},
        env={},
    )


def _node_ctx(config: dict, eval_context: EvalContext, inputs: dict | None = None) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="end-mvxuwqo7-1",
        node_type=NodeType.END.value,
        inputs=inputs or {},
        config=config,
        env=env,
        services=ServiceRegistry(),
        eval_context=eval_context,
        evaluator=ExpressionEvaluator(),
    )


def test_eval_expression_hyphenated_node_ref() -> None:
    evaluator = ExpressionEvaluator().template
    ctx = _ctx_with_outputs({"llm-mvxuv1f2-1": {"output": "你好"}})

    assert evaluator.eval_expression("llm-mvxuv1f2-1.output.output", ctx) == "你好"


def test_eval_template_interpolates_hyphenated_ref() -> None:
    evaluator = ExpressionEvaluator().template
    ctx = _ctx_with_outputs({"start-1": {"input": "张三"}})

    assert evaluator.eval_template("客户：{{start-1.output.input}}", ctx) == "客户：张三"


def test_lint_allows_hyphenated_node_ref() -> None:
    raw = {
        "nodes": [
            {"id": "start-1", "type": "1", "data": {}},
            {
                "id": "llm-mvxuv1f2-1",
                "type": "3",
                "data": {
                    "inputs": {
                        "modleName": "deepseek",
                        "prompt": "hi",
                    },
                },
            },
            {
                "id": "end-mvxuwqo7-1",
                "type": "2",
                "data": {"inputs": {"content": "{{llm-mvxuv1f2-1.output.output}}"}},
            },
        ],
        "edges": [
            {"sourceNodeID": "start-1", "targetNodeID": "llm-mvxuv1f2-1"},
            {"sourceNodeID": "llm-mvxuv1f2-1", "targetNodeID": "end-mvxuwqo7-1"},
        ],
    }

    issues = validate_raw_graph(raw)
    assert not any(i.code == "expression_syntax" for i in issues)


def test_lint_still_flags_real_syntax_error() -> None:
    raw = {
        "nodes": [
            {"id": "start-1", "type": "1", "data": {}},
            {"id": "end-1", "type": "2", "data": {"inputs": {"content": "{{1 + }}"}}},
        ],
        "edges": [{"sourceNodeID": "start-1", "targetNodeID": "end-1"}],
    }

    issues = validate_raw_graph(raw)
    assert any(i.code == "expression_syntax" for i in issues)


def test_llm_prompt_interpolates_hyphenated_ref() -> None:
    ctx = _node_ctx(
        config={"modleName": "deepseek", "prompt": "客户：{{start-1.output.input}}"},
        eval_context=_ctx_with_outputs({"start-1": {"input": "张三"}}),
        inputs={"input": "张师傅"},
    )

    result = asyncio.run(LLMNodeHandler().run(ctx))

    # 未注入 llm 服务时返回 stub，prompt 原文（截断 80 字符）应已插值
    assert "客户：张三" in result.outputs["output"]
    assert "{{" not in result.outputs["output"]


def test_end_node_outputs_resolved_content_template() -> None:
    ctx = _node_ctx(
        config={"content": "{{llm-mvxuv1f2-1.output.output}}"},
        eval_context=_ctx_with_outputs({"llm-mvxuv1f2-1": {"output": "您好，张三！"}}),
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"output": "您好，张三！"}


def test_end_node_keeps_input_parameters_behavior() -> None:
    # coze 格式：END 用 inputParameters 声明输出，inputs 非空时优先原样输出
    ctx = _node_ctx(
        config={"content": "{{output}}"},
        eval_context=_ctx_with_outputs({}),
        inputs={"output": "上游结果"},
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"output": "上游结果"}
