"""对话流节点测试：输出节点（13）与问答节点（18）。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from internal.domain.canvas.expression import EvalContext, ExpressionEvaluator
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes import question as question_module
from internal.domain.graph.nodes.end import EndNodeHandler
from internal.domain.graph.nodes.input import InputNodeHandler
from internal.domain.graph.nodes.output import OutputNodeHandler
from internal.domain.graph.nodes.question import QuestionNodeHandler


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.appended = []

    async def append(self, message):
        self.appended.append(message)
        return replace(message, message_id=uuid4())


def _make_env(conversation_id=None) -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="chatflow-test",
        application_id=uuid4(),
        conversation_id=conversation_id,
    )


def _eval_context(node_outputs: dict | None = None) -> EvalContext:
    return EvalContext(
        input={},
        node_outputs=node_outputs or {},
        globals={},
        env={},
    )


def test_output_node_renders_template_and_emits_message():
    conv_id = uuid4()
    repo = _FakeMessageRepo()
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    ctx = NodeContext(
        node_id="output_1",
        node_type="13",
        inputs={},
        config={"content": "你好 {{start_1.output.USER_INPUT}}"},
        env=_make_env(conversation_id=conv_id),
        services=ServiceRegistry({"message_repo": repo}),
        eval_context=_eval_context({"start_1": {"USER_INPUT": "小明"}}),
        evaluator=ExpressionEvaluator(),
        emit_event=emit,
    )

    result = asyncio.run(OutputNodeHandler().run(ctx))

    assert result.outputs["output"] == "你好 小明"
    assert events[0][0] == "output_message"
    assert events[0][1]["content"] == "你好 小明"
    assert repo.appended[0].conversation_id == conv_id
    assert repo.appended[0].role == "assistant"


def test_output_node_without_conversation_skips_persistence():
    repo = _FakeMessageRepo()
    ctx = NodeContext(
        node_id="output_1",
        node_type="13",
        inputs={},
        config={"content": "hi"},
        env=_make_env(),
        services=ServiceRegistry({"message_repo": repo}),
    )

    result = asyncio.run(OutputNodeHandler().run(ctx))

    assert result.outputs["output"] == "hi"
    assert repo.appended == []


def test_question_node_interrupts_with_question_and_options(monkeypatch):
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"answer": "选项 A"}

    monkeypatch.setattr(question_module, "interrupt", fake_interrupt)

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={"question": "请选择", "options": "选项 A\n选项 B"},
        env=_make_env(conversation_id=uuid4()),
        services=ServiceRegistry(),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert captured["type"] == "question"
    assert captured["question"] == "请选择"
    assert captured["options"] == ["选项 A", "选项 B"]
    assert result.outputs["answer"] == "选项 A"


def test_question_node_accepts_plain_answer(monkeypatch):
    monkeypatch.setattr(question_module, "interrupt", lambda payload: "自由输入")

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={"question": "请输入"},
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert result.outputs["answer"] == "自由输入"
    assert result.outputs["question"] == "请输入"


def test_question_node_defaults_to_direct_without_options(monkeypatch):
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return "自由文本"

    monkeypatch.setattr(question_module, "interrupt", fake_interrupt)

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={"question": "请输入"},
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert captured["answer_type"] == "direct"
    assert captured["options"] == []
    assert result.outputs["USER_RESPONSE"] == "自由文本"
    assert result.outputs["QUESTION_DATA"] == [{"content_type": "text", "content": "自由文本"}]


def test_question_node_options_mode_exposes_choices(monkeypatch):
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"content": "A"}

    monkeypatch.setattr(question_module, "interrupt", fake_interrupt)

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={
            "question": "请选择",
            "answerType": "options",
            "options": ["A", "B"],
        },
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert captured["answer_type"] == "options"
    assert captured["options"] == ["A", "B"]
    assert result.outputs["answer"] == "A"


def test_question_node_extract_mode_returns_structured_fields(monkeypatch):
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return "我叫小明，今年 18 岁"

    class _FakeLLM:
        async def chat(self, **kwargs):
            return SimpleNamespace(content='{"name": "小明", "age": 18}')

    monkeypatch.setattr(question_module, "interrupt", fake_interrupt)

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={
            "question": "请介绍自己",
            "answerType": "extract",
            "extractFields": "name\nage",
            "modleName": "test-model",
        },
        env=_make_env(),
        services=ServiceRegistry({"llm": _FakeLLM()}),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert captured["answer_type"] == "extract"
    assert captured["extract_fields"] == ["name", "age"]
    assert result.outputs["extracted"] == {"name": "小明", "age": 18}
    assert "error" not in result.outputs


def test_question_node_extract_without_model_reports_error(monkeypatch):
    monkeypatch.setattr(question_module, "interrupt", lambda payload: "随便说说")

    ctx = NodeContext(
        node_id="question_1",
        node_type="18",
        inputs={},
        config={
            "question": "请介绍自己",
            "answerType": "extract",
            "extractFields": ["name"],
        },
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(QuestionNodeHandler().run(ctx))

    assert "未配置模型" in result.outputs["error"]
    assert "extracted" not in result.outputs


def test_input_node_reuses_question_interrupt_as_direct_text(monkeypatch):
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"answer": "用户输入"}

    monkeypatch.setattr(question_module, "interrupt", fake_interrupt)

    ctx = NodeContext(
        node_id="input_1",
        node_type="30",
        inputs={},
        config={"prompt": "请输入姓名"},
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(InputNodeHandler().run(ctx))

    assert captured["type"] == "question"
    assert captured["question"] == "请输入姓名"
    assert captured["answer_type"] == "direct"
    assert captured["options"] == []
    assert result.outputs["USER_RESPONSE"] == "用户输入"


def test_output_node_renders_output_variables():
    ctx = NodeContext(
        node_id="output_1",
        node_type="13",
        inputs={},
        config={
            "content": "完成",
            "outputVariables": [
                {"key": "user_name", "value": "{{start_1.output.USER_INPUT}}"},
                {"key": "fixed", "value": "常量"},
            ],
        },
        env=_make_env(),
        services=ServiceRegistry(),
        eval_context=_eval_context({"start_1": {"USER_INPUT": "小明"}}),
        evaluator=ExpressionEvaluator(),
    )

    result = asyncio.run(OutputNodeHandler().run(ctx))

    assert result.outputs["output"] == "完成"
    assert result.outputs["user_name"] == "小明"
    assert result.outputs["fixed"] == "常量"


def test_end_node_returns_rendered_text_and_streams():
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    ctx = NodeContext(
        node_id="end_1",
        node_type="2",
        inputs={},
        config={
            "returnType": "text",
            "content": "回答：{{llm_1.output.output}}",
            "stream": True,
        },
        env=_make_env(),
        services=ServiceRegistry(),
        eval_context=_eval_context({"llm_1": {"output": "你好"}}),
        evaluator=ExpressionEvaluator(),
        emit_event=emit,
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"output": "回答：你好"}
    assert events == [
        (
            "output_message",
            {
                "content": "回答：你好",
                "role": "assistant",
                "stream": True,
            },
        )
    ]


def test_end_node_stream_persists_assistant_message():
    conv_id = uuid4()
    repo = _FakeMessageRepo()

    async def emit(event_type: str, payload: dict) -> None:
        return None

    ctx = NodeContext(
        node_id="end_1",
        node_type="2",
        inputs={},
        config={"returnType": "text", "content": "最终回答", "stream": True},
        env=_make_env(conversation_id=conv_id),
        services=ServiceRegistry({"message_repo": repo}),
        emit_event=emit,
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"output": "最终回答"}
    assert len(repo.appended) == 1
    assert repo.appended[0].role == "assistant"
    assert repo.appended[0].content == "最终回答"
    assert repo.appended[0].metadata["source"] == "end_node"


def test_end_node_non_stream_does_not_persist():
    repo = _FakeMessageRepo()
    ctx = NodeContext(
        node_id="end_1",
        node_type="2",
        inputs={},
        config={"returnType": "text", "content": "普通回答"},
        env=_make_env(conversation_id=uuid4()),
        services=ServiceRegistry({"message_repo": repo}),
    )

    asyncio.run(EndNodeHandler().run(ctx))

    assert repo.appended == []


def test_end_node_variables_mode_returns_inputs():
    ctx = NodeContext(
        node_id="end_1",
        node_type="2",
        inputs={"answer": "A", "score": 1},
        config={"returnType": "variables"},
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"answer": "A", "score": 1}


def test_end_node_legacy_inputs_without_return_type():
    ctx = NodeContext(
        node_id="end_1",
        node_type="2",
        inputs={"content": "ok"},
        config={},
        env=_make_env(),
        services=ServiceRegistry(),
    )

    result = asyncio.run(EndNodeHandler().run(ctx))

    assert result.outputs == {"content": "ok"}
