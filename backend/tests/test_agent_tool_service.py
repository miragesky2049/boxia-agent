"""M4-c PRD F14.2：智能体即工具 AgentToolService（describe 合成 + invoke 归因/链防护）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from internal.application.apps.agent_tool_service import AgentToolService
from internal.application.apps.call_chain import MAX_CALL_CHAIN_DEPTH

_TARGET = uuid4()
_PARENT = uuid4()


class _FakeAppService:
    def __init__(
        self,
        cards: dict[str, dict],
        published: dict[str, int | None] | None = None,
    ) -> None:
        self._cards = cards
        self._published = published if published is not None else {str(_TARGET): 3}

    def get_visible_app_for_user(self, application_id, tenant_id, user_id):
        return self._cards.get(str(application_id))

    def get_published_graph_version(self, application_id):
        return self._published.get(str(application_id))


class _FakeRunner:
    def __init__(self, output: Any) -> None:
        self._output = output
        self.inputs: dict | None = None

    async def invoke(self, start_inputs: dict) -> Any:
        self.inputs = start_inputs
        return self._output


class _FakeRunnerFactory:
    def __init__(self, output: Any = "专家回答") -> None:
        self.output = output
        self.calls: list[dict] = []
        self.runners: list[_FakeRunner] = []

    async def __call__(self, service, uow, context, **kwargs) -> _FakeRunner:
        self.calls.append(kwargs)
        runner = _FakeRunner(self.output)
        self.runners.append(runner)
        return runner


def _card(**overrides: Any) -> dict:
    card = {
        "id": str(_TARGET),
        "name": "报销专家",
        "description": "处理差旅报销制度咨询",
        "flow_type": "agent",
    }
    card.update(overrides)
    return card


def _service(
    *,
    cards: dict[str, dict] | None = None,
    published: dict[str, int | None] | None = None,
    output: Any = "专家回答",
    user_id: Any = "auto",
) -> tuple[AgentToolService, _FakeRunnerFactory]:
    cards = {str(_TARGET): _card()} if cards is None else cards
    factory = _FakeRunnerFactory(output)
    svc = AgentToolService(
        _FakeAppService(cards, published),
        factory,
        uow=object(),
        context=object(),
        tenant_id=uuid4(),
        user_id=uuid4() if user_id == "auto" else user_id,
        parent_run_id=_PARENT,
    )
    return svc, factory


# ---------- describe：合成名/描述/固定 question schema ----------
def test_describe_agent_prefixed_name_and_question_schema() -> None:
    svc, _ = _service(cards={str(_TARGET): _card(name="Expense Expert")})
    described = asyncio.run(svc.describe(str(_TARGET), []))
    assert described is not None
    assert described["name"] == "agent_expense_expert"
    assert "报销制度" in described["description"] or "Expense" in described["description"]
    # 子代理输入就是一句话：固定 question schema，不读目标 start 参数（F14.2）
    assert described["parameters"]["required"] == ["question"]
    assert described["parameters"]["properties"]["question"]["type"] == "string"


def test_describe_non_ascii_name_falls_back_to_app_id_slug() -> None:
    svc, _ = _service()
    described = asyncio.run(svc.describe(str(_TARGET), []))
    assert described is not None
    assert described["name"].startswith("agent_")
    assert described["name"] == f"agent_{str(_TARGET).replace('-', '')[:12]}"


def test_describe_respects_tool_name_and_description_overrides() -> None:
    svc, _ = _service()
    described = asyncio.run(
        svc.describe(
            str(_TARGET),
            [],
            tool_name="ask_expense_bot",
            description="只答报销额度问题",
        )
    )
    assert described is not None
    assert described["name"] == "ask_expense_bot"
    assert "只答报销额度问题" in described["description"]


@pytest.mark.parametrize(
    "case",
    ["invisible", "wrong_flow_type", "unpublished", "bad_uuid", "no_user"],
)
def test_describe_unavailable_returns_none(case: str) -> None:
    if case == "invisible":
        svc, _ = _service(cards={})
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None
    elif case == "wrong_flow_type":
        svc, _ = _service(cards={str(_TARGET): _card(flow_type="workflow")})
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None
    elif case == "unpublished":
        svc, _ = _service(published={str(_TARGET): None})
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None
    elif case == "bad_uuid":
        svc, _ = _service()
        assert asyncio.run(svc.describe("not-a-uuid", [])) is None
    else:
        svc, _ = _service(user_id=None)
        assert asyncio.run(svc.describe(str(_TARGET), [])) is None


# ---------- invoke：子 run 归因 / 链下传 / thread 隔离 ----------
def test_invoke_runs_child_with_parent_and_chain() -> None:
    svc, factory = _service()
    observation = asyncio.run(
        svc.invoke(str(_TARGET), {"question": "差旅住宿标准是多少？"}, ["ancestor-wf"])
    )
    assert observation == "专家回答"

    call = factory.calls[0]
    assert call["application_id"] == _TARGET
    assert call["parent_run_id"] == _PARENT
    # F14.2 thread 口径：{parent}:sub:{app_id}，与父会话 checkpoint 隔离（R22）
    assert call["thread_id"] == f"{_PARENT}:sub:{_TARGET}"
    # 入参即一句话；不传 history（委派语义要求问题自包含，F14.5）
    assert factory.runners[0].inputs == {
        "input": "差旅住宿标准是多少？",
        "workflow_chain": ["ancestor-wf", str(_TARGET)],
    }


def test_invoke_accepts_common_argument_key_misfires() -> None:
    svc, factory = _service()
    asyncio.run(svc.invoke(str(_TARGET), {"text": "报销上限"}, []))
    assert factory.runners[0].inputs["input"] == "报销上限"


def test_invoke_detects_cycle() -> None:
    svc, factory = _service()
    with pytest.raises(RuntimeError, match="循环调用"):
        asyncio.run(svc.invoke(str(_TARGET), {"question": "q"}, [str(_TARGET)]))
    assert factory.calls == []


def test_invoke_detects_max_depth() -> None:
    svc, factory = _service()
    chain = [str(uuid4()) for _ in range(MAX_CALL_CHAIN_DEPTH)]
    with pytest.raises(RuntimeError, match="深度"):
        asyncio.run(svc.invoke(str(_TARGET), {"question": "q"}, chain))
    assert factory.calls == []


def test_invoke_unavailable_target_raises_for_model_self_correction() -> None:
    svc, factory = _service(published={str(_TARGET): None})
    with pytest.raises(RuntimeError, match="不可用"):
        asyncio.run(svc.invoke(str(_TARGET), {"question": "q"}, []))
    assert factory.calls == []


def test_invoke_requires_non_empty_question() -> None:
    svc, factory = _service()
    with pytest.raises(RuntimeError, match="问题不能为空"):
        asyncio.run(svc.invoke(str(_TARGET), {"question": "  "}, []))
    assert factory.calls == []


# ---------- observation 文本形态 ----------
def test_observation_text_forms() -> None:
    svc, _ = _service(output={"answer": "上限 500 元"})
    assert asyncio.run(svc.invoke(str(_TARGET), {"question": "q"}, [])) == "上限 500 元"

    svc_dict, _ = _service(output={"nodes": {"x": 1}})
    text = asyncio.run(svc_dict.invoke(str(_TARGET), {"question": "q"}, []))
    assert text == json.dumps({"nodes": {"x": 1}}, ensure_ascii=False)

    svc_empty, _ = _service(output="")
    assert (
        asyncio.run(svc_empty.invoke(str(_TARGET), {"question": "q"}, []))
        == "智能体「报销专家」无文本输出"
    )

    svc_none, _ = _service(output=None)
    assert (
        asyncio.run(svc_none.invoke(str(_TARGET), {"question": "q"}, []))
        == "智能体「报销专家」执行完成，无文本输出"
    )
