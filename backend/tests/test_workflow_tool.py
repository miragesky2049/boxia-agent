"""0074 PRD F7：工作流即工具（domain schema 提取 + application 服务环/深度/归因）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from internal.application.apps.workflow_tool_service import (
    MAX_WORKFLOW_TOOL_DEPTH,
    WorkflowToolService,
)
from internal.domain.canvas.workflow_tool import build_start_input_schema


# ---------- domain：build_start_input_schema ----------
def _graph_with_start(params: Any) -> dict:
    return {
        "nodes": [
            {
                "type": "1",
                "data": {"inputs": {"params": {"value": {"type": "literal", "content": params}}}},
            },
        ],
        "edges": [],
    }


def test_start_schema_maps_types_and_required() -> None:
    graph = _graph_with_start(
        [
            {"name": "order_no", "type": "string", "description": "订单号"},
            {"name": "amount", "type": "number", "required": False},
            {"name": "urgent", "type": "bool"},
            {"name": "weird", "type": "unknown-type"},
        ]
    )
    schema = build_start_input_schema(graph)
    assert schema["type"] == "object"
    assert schema["properties"]["order_no"] == {"type": "string", "description": "订单号"}
    assert schema["properties"]["amount"] == {"type": "number"}
    assert schema["properties"]["urgent"]["type"] == "boolean"
    # 未知类型收口 string；required 缺省 True，显式 False 不入必填
    assert schema["properties"]["weird"]["type"] == "string"
    assert schema["required"] == ["order_no", "urgent", "weird"]


def test_start_schema_missing_start_or_params() -> None:
    assert build_start_input_schema({"nodes": []}) == {"type": "object", "properties": {}}
    assert build_start_input_schema(_graph_with_start([])) == {"type": "object", "properties": {}}


# ---------- application：WorkflowToolService ----------
class _FakeAppService:
    def __init__(self, cards: dict[str, dict], graphs: dict[str, dict]) -> None:
        self._cards = cards
        self._graphs = graphs

    def get_visible_app_for_user(self, application_id, tenant_id, user_id):
        return self._cards.get(str(application_id))

    async def get_runtime_graph(self, application_id, tenant_id=None):
        return self._graphs[str(application_id)]


class _FakeRunner:
    def __init__(self, output: Any) -> None:
        self._output = output
        self.inputs: dict | None = None

    async def invoke(self, start_inputs: dict) -> Any:
        self.inputs = start_inputs
        return self._output


class _FakeRunnerFactory:
    def __init__(self, output: Any = "done") -> None:
        self.output = output
        self.calls: list[dict] = []
        self.runners: list[_FakeRunner] = []

    async def __call__(self, service, uow, context, **kwargs) -> _FakeRunner:
        self.calls.append(kwargs)
        runner = _FakeRunner(self.output)
        self.runners.append(runner)
        return runner


def _service(
    *,
    cards: dict[str, dict] | None = None,
    graphs: dict[str, dict] | None = None,
    output: Any = "done",
) -> tuple[WorkflowToolService, _FakeRunnerFactory]:
    app_id = str(_TARGET)
    cards = (
        {
            app_id: {
                "id": app_id,
                "name": "退款流程",
                "description": "按订单退款",
                "flow_type": "workflow",
            }
        }
        if cards is None
        else cards
    )
    graphs = (
        {app_id: _graph_with_start([{"name": "order_no", "type": "string"}])}
        if graphs is None
        else graphs
    )
    factory = _FakeRunnerFactory(output)
    svc = WorkflowToolService(
        _FakeAppService(cards, graphs),
        factory,
        uow=object(),
        context=object(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        parent_run_id=_PARENT,
    )
    return svc, factory


_TARGET = uuid4()
_PARENT = uuid4()


def test_describe_returns_card_and_start_schema() -> None:
    svc, _ = _service()
    described = asyncio.run(svc.describe(str(_TARGET), []))
    assert described is not None
    assert described["name"] == "退款流程"
    assert described["parameters"]["properties"]["order_no"]["type"] == "string"


@pytest.mark.parametrize("mutate", ["invisible", "wrong_type", "bad_uuid"])
def test_describe_unavailable_returns_none(mutate: str) -> None:
    if mutate == "invisible":
        svc, _ = _service(cards={})
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None
    elif mutate == "wrong_type":
        svc, _ = _service(
            cards={str(_TARGET): {"id": str(_TARGET), "name": "n", "flow_type": "agent"}}
        )
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None
    else:
        svc, _ = _service()
        assert asyncio.run(svc.describe("not-a-uuid", [])) is None


def test_invoke_runs_child_with_parent_and_chain() -> None:
    svc, factory = _service(output="退款成功")
    observation = asyncio.run(svc.invoke(str(_TARGET), {"order_no": "A1"}, ["ancestor-wf"]))
    assert observation == "退款成功"

    call = factory.calls[0]
    assert call["application_id"] == _TARGET
    assert call["parent_run_id"] == _PARENT
    assert call["thread_id"] == f"wf-tool:{_PARENT}:{_TARGET}"
    # 入参=start 变量，链下传（本应用 ID 追加在尾部供孙代判环）
    assert factory.runners[0].inputs == {
        "order_no": "A1",
        "workflow_chain": ["ancestor-wf", str(_TARGET)],
    }


def test_invoke_detects_cycle() -> None:
    svc, factory = _service()
    with pytest.raises(RuntimeError, match="循环调用"):
        asyncio.run(svc.invoke(str(_TARGET), {}, [str(_TARGET)]))
    assert factory.calls == []


def test_invoke_detects_max_depth() -> None:
    svc, factory = _service()
    chain = [str(uuid4()) for _ in range(MAX_WORKFLOW_TOOL_DEPTH)]
    with pytest.raises(RuntimeError, match="深度"):
        asyncio.run(svc.invoke(str(_TARGET), {}, chain))
    assert factory.calls == []


def test_invoke_unavailable_target_raises_for_model_self_correction() -> None:
    svc, factory = _service(cards={})
    with pytest.raises(RuntimeError, match="不可用"):
        asyncio.run(svc.invoke(str(_TARGET), {}, []))
    assert factory.calls == []


def test_observation_text_forms() -> None:
    svc, factory = _service(output={"answer": "ok", "count": 2})
    assert asyncio.run(svc.invoke(str(_TARGET), {}, [])) == json.dumps(
        {"answer": "ok", "count": 2}, ensure_ascii=False
    )

    svc_empty_str, _ = _service(output="")
    assert asyncio.run(svc_empty_str.invoke(str(_TARGET), {}, [])) == "（工作流无输出）"

    svc_none, _ = _service(output=None)
    assert (
        asyncio.run(svc_none.invoke(str(_TARGET), {}, []))
        == "工作流「退款流程」执行完成，无文本输出"
    )
