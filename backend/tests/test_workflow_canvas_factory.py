"""workflow 画布工厂自检：三幅最小图必须可转换，无人审图必须能跑通 runtime。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from internal.domain.canvas.convert import convert_canvas
from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.graph.runtime import GraphRuntime
from tests.workflow_canvas import (
    build_start_end_canvas,
    build_start_human_end_canvas,
    build_start_llm_end_canvas,
)


class FakeLLMService:
    async def chat(
        self, *, messages, model, temperature=None, max_tokens=None, response_format=None
    ):
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        return SimpleNamespace(
            content=f"fake reply to: {messages[-1]['content']}", model=model, usage=usage
        )


class FakeRunRepo:
    def insert_run(self, **kwargs: Any) -> None:
        pass

    def update_run_status(
        self, run_id: Any, execute_status: str, output=None, error_message=None
    ) -> None:
        pass

    def update_run_interrupt(self, run_id: Any, payload: dict) -> None:
        pass

    def insert_node_execution(self, **kwargs: Any) -> None:
        pass


class FakeUsageRepo:
    def record_usage(self, **kwargs: Any) -> None:
        pass


def _runtime(canvas_json: dict, services: ServiceRegistry | None = None) -> GraphRuntime:
    return GraphRuntime(
        canvas_json=canvas_json,
        services=services or ServiceRegistry({}),
        run_repo=FakeRunRepo(),
        usage_repo=FakeUsageRepo(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        application_id=uuid4(),
        checkpointer=None,
    )


def test_three_canvases_convert():
    for canvas in (
        build_start_end_canvas(),
        build_start_llm_end_canvas(),
        build_start_human_end_canvas(),
    ):
        graph = convert_canvas(canvas)
        assert graph.nodes, "转换后至少有节点"


def test_start_end_runs_through():
    output = asyncio.run(_runtime(build_start_end_canvas()).invoke({"input": "直出内容"}))
    assert output.get("output") == "直出内容"


def test_start_llm_end_runs_through():
    output = asyncio.run(
        _runtime(
            build_start_llm_end_canvas(),
            ServiceRegistry({"llm": FakeLLMService()}),
        ).invoke({"topic": "写一首诗"})
    )
    assert "写一首诗" in output.get("output", "")


def test_human_canvas_carries_assignee_role():
    graph = convert_canvas(
        build_start_human_end_canvas(assignee_role="finance", instructions="财务复核")
    )
    human = next(n for n in graph.nodes if n.type == "60")
    assert human.config["assignee_role"] == "finance"
    assert human.config["instructions"] == "财务复核"
