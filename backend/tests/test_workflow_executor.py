"""Workflow DAG 执行器单元测试：用 stub LLM 跑通最小图与异常分支。"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from internal.application.errors import ValidationError
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.engine.llm import LLMClient, LLMResponse, LLMUsage
from internal.engine.workflow.executor import WorkflowExecutor
from internal.engine.workflow.validator import GraphValidationError, validate_graph


class StubLLM(LLMClient):
    """按预设 content 返回响应；记录调用次数便于断言。"""

    def __init__(self, content: str = "stub-answer") -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: Any = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages})
        return LLMResponse(
            content=self._content,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub-model",
        )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _minimal_graph(llm_content: str = "stub-answer") -> dict:
    """Start → LLM → End 最小图。"""
    return {
        "variables": [{"key": "query", "type": "string", "required": True}],
        "nodes": [
            {"id": "start_1", "type": "start", "data": {}},
            {
                "id": "llm_1",
                "type": "llm",
                "data": {
                    "system_prompt_tpl": "",
                    "user_prompt_tpl": "{{query}}",
                    "temperature": 0.7,
                },
            },
            {
                "id": "end_1",
                "type": "end",
                "data": {"output_tpl": {"answer": "{{llm_1.output}}"}},
            },
        ],
        "edges": [
            {"source": "start_1", "target": "llm_1"},
            {"source": "llm_1", "target": "end_1"},
        ],
    }


def test_validator_rejects_cycle_and_bad_type() -> None:
    """图校验：环、非法节点类型、多 start 均被拒。"""
    with pytest.raises(GraphValidationError, match="环"):
        validate_graph(
            {
                "nodes": [
                    {"id": "s", "type": "start"},
                    {"id": "l", "type": "llm"},
                    {"id": "e", "type": "end"},
                ],
                "edges": [
                    {"source": "s", "target": "l"},
                    {"source": "l", "target": "s"},
                    {"source": "l", "target": "e"},
                ],
            }
        )

    with pytest.raises(GraphValidationError, match="类型非法"):
        validate_graph(
            {
                "nodes": [
                    {"id": "s", "type": "start"},
                    {"id": "x", "type": "if_else"},
                    {"id": "e", "type": "end"},
                ],
                "edges": [],
            }
        )

    with pytest.raises(GraphValidationError, match="必须恰好 1 个 start"):
        validate_graph(
            {
                "nodes": [
                    {"id": "s1", "type": "start"},
                    {"id": "s2", "type": "start"},
                    {"id": "e", "type": "end"},
                ],
                "edges": [],
            }
        )


def test_executor_runs_minimal_graph_with_stub_llm() -> None:
    """最小图跑通：LLM 输出经 End 节点模板组装为最终 outputs。"""
    stub = StubLLM(content="stub-answer")
    executor = WorkflowExecutor(llm_factory=lambda _data: stub)

    result = _run(
        executor.run(
            workflow_id=uuid4(),
            tenant_id=PLATFORM_TENANT_ID,
            user_id=None,
            graph=_minimal_graph(),
            global_inputs={"query": "世界"},
        )
    )

    assert result.finish_reason == "success"
    assert result.outputs == {"answer": "stub-answer"}
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert len(result.node_states) == 3
    status_by_id = {state.node_id: state.status for state in result.node_states}
    assert status_by_id == {"start_1": "success", "llm_1": "success", "end_1": "success"}
    # LLM 收到的 user prompt 应该已经把 {{query}} 替换为 "世界"
    sent_messages = stub.calls[0]["messages"]
    assert sent_messages[-1]["content"] == "世界"


def test_executor_rejects_missing_required_input() -> None:
    """缺少必填变量时直接 422 风格 ValidationError。"""
    executor = WorkflowExecutor(llm_factory=lambda _data: StubLLM())

    with pytest.raises(ValidationError, match="缺少必填入参：query"):
        _run(
            executor.run(
                workflow_id=uuid4(),
                tenant_id=PLATFORM_TENANT_ID,
                user_id=None,
                graph=_minimal_graph(),
                global_inputs={},
            )
        )


def test_executor_marks_node_error_on_llm_failure() -> None:
    """LLM 抛错时整图 finish_reason=error，节点状态标红。"""

    class BrokenLLM(LLMClient):
        async def chat(self, **_kwargs: Any) -> LLMResponse:
            raise RuntimeError("上游网关 500")

    executor = WorkflowExecutor(llm_factory=lambda _data: BrokenLLM())

    result = _run(
        executor.run(
            workflow_id=uuid4(),
            tenant_id=PLATFORM_TENANT_ID,
            user_id=None,
            graph=_minimal_graph(),
            global_inputs={"query": "hi"},
        )
    )

    assert result.finish_reason == "error"
    error_state = next(state for state in result.node_states if state.node_id == "llm_1")
    assert error_state.status == "error"
    assert "上游网关 500" in error_state.error
