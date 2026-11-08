"""对话流运行期落库一致性：run_id 统一、用户消息、最终回答、中断问题。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import web.deps.graph as graph_deps
from internal.application.apps.chat_service import ChatflowPreparedRun, ChatService
from internal.domain.graph.runtime import GraphInterrupted, GraphRuntime


class _FakeRunRepo:
    def __init__(self, existing: dict | None = None) -> None:
        self.runs = {k: {"id": k} for k in (existing or {})}
        self.inserted: list[dict] = []

    def get_run(self, run_id):
        return self.runs.get(run_id)

    def get_running_by_thread(self, tenant_id, application_id, thread_id):
        return next(iter(self.runs.values()), None)

    def insert_run(self, **kwargs):
        self.inserted.append(kwargs)
        self.runs[kwargs["run_id"]] = {"id": kwargs["run_id"]}


class _NoGetRunRepo:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    def insert_run(self, **kwargs):
        self.inserted.append(kwargs)


def test_ensure_run_inserts_once():
    tenant_id, application_id, run_id = uuid4(), uuid4(), uuid4()
    repo = _FakeRunRepo()
    runtime = GraphRuntime(
        {},
        run_repo=repo,
        tenant_id=tenant_id,
        application_id=application_id,
        run_id=run_id,
        thread_id="conv-1",
    )

    runtime.ensure_run({"USER_INPUT": "你好"})
    runtime.ensure_run({"USER_INPUT": "你好"})

    assert len(repo.inserted) == 1
    record = repo.inserted[0]
    assert record["run_id"] == run_id
    assert record["tenant_id"] == tenant_id
    assert record["workflow_id"] == application_id
    assert record["thread_id"] == "conv-1"
    assert record["input_data"] == {"USER_INPUT": "你好"}


def test_ensure_run_inserts_when_repo_has_no_get_run():
    repo = _NoGetRunRepo()
    runtime = GraphRuntime({}, run_repo=repo, thread_id="conv-1")

    runtime.ensure_run({"resume": {"answer": "A"}})

    assert len(repo.inserted) == 1
    assert repo.inserted[0]["input_data"] == {"resume": {"answer": "A"}}


def test_ensure_run_skips_without_repo():
    GraphRuntime({}, thread_id="conv-1").ensure_run({"USER_INPUT": "hi"})


def test_build_runner_uses_one_run_id_everywhere(monkeypatch):
    tenant_id, application_id, user_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    captured: dict = {}

    class _FakeService:
        async def get_runtime_graph(self, app_id, tid):
            return {}

        def build_runtime_variables(self, app_id, uid):
            return {}, set()

    class _FakeToolExecutor:
        def __init__(self, *args, **kwargs):
            captured["tool_run_id"] = kwargs.get("run_id")

    class _FakeAsyncMessageRepository:
        def __init__(self, *args, **kwargs):
            captured["message_run_id"] = kwargs.get("run_id")

    class _FakeAsyncConversationRepository:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(graph_deps, "ToolExecutorService", _FakeToolExecutor)
    monkeypatch.setattr(graph_deps, "AsyncMessageRepository", _FakeAsyncMessageRepository)
    monkeypatch.setattr(
        graph_deps,
        "AsyncConversationRepository",
        _FakeAsyncConversationRepository,
    )
    monkeypatch.setattr(graph_deps, "register_retrieval_services", lambda services: None)

    uow = SimpleNamespace(session=object())
    runtime = asyncio.run(
        graph_deps.build_runner(
            _FakeService(),
            uow,
            None,
            tenant_id=tenant_id,
            application_id=application_id,
            thread_id="conv-1",
            run_id=run_id,
            current_user_id=user_id,
        )
    )

    assert runtime.run_id == run_id
    assert captured["tool_run_id"] == run_id
    assert captured["message_run_id"] == run_id


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def append_message(self, **kwargs):
        self.messages.append(kwargs)


class _FakeConvRepo:
    def __init__(self) -> None:
        self.touched: list = []

    def touch(self, conversation_id):
        self.touched.append(conversation_id)


class _FakeUow:
    def __init__(self) -> None:
        self.session = object()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeRunner:
    def __init__(
        self,
        run_id,
        thread_id,
        application_id,
        *,
        output=None,
        emitted_text: str | None = None,
        interrupt: GraphInterrupted | None = None,
        on_event=None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.application_id = application_id
        self.output = output
        self.emitted_text = emitted_text
        self.interrupt = interrupt
        self.on_event = on_event
        self.ensure_inputs = None
        self.invoked = None
        self.resumed = None

    def ensure_run(self, data):
        self.ensure_inputs = data

    async def list_state_history(self, limit=1):
        return []

    async def invoke(self, data):
        self.invoked = data
        if self.emitted_text is not None and self.on_event is not None:
            await self.on_event("output_message", {"content": self.emitted_text})
        if self.interrupt is not None:
            raise self.interrupt
        return self.output

    async def resume(self, payload):
        self.resumed = payload
        return self.output


def _service(runner_factory=None, run_repo=None) -> ChatService:
    service = object.__new__(ChatService)
    service._tenant_id = uuid4()
    service._user_id = uuid4()
    service._principal = SimpleNamespace(username="tester")
    service._context = SimpleNamespace()
    service._app_service = SimpleNamespace()
    service._uow = _FakeUow()
    service._conv_repo = _FakeConvRepo()
    service._msg_repo = _FakeMessageRepo()
    service._runner_factory = runner_factory
    # DDD 四期：run 仓储与默认模型改为构造注入，测试里直接赋值等价属性
    service._run_repo = run_repo if run_repo is not None else _FakeRunRepo()
    service._model_service = SimpleNamespace()
    service._resource_service = SimpleNamespace()
    service._default_llm_model_id = "test-model"
    return service


def _prepared(application_id, *, message="你好", resume=None) -> ChatflowPreparedRun:
    return ChatflowPreparedRun(
        application_id=application_id,
        message=message,
        conversation_id=uuid4(),
        conversation_title="会话",
        thread_id="conv-1",
        resume=resume,
    )


def _make_runner_factory(runner: _FakeRunner) -> tuple[dict, Any]:
    """构造注入 ChatService._runner_factory 的假工厂；返回 (捕获的 kwargs, 工厂)。"""
    seen: dict = {}

    async def fake_factory(service, uow, context, **kwargs):
        seen.update(kwargs)
        runner.on_event = kwargs.get("on_node_event")
        return runner

    return seen, fake_factory


def _collect(service, prepared) -> list[tuple[str, dict]]:
    async def run():
        return [event async for event in service.run_chatflow_stream(prepared)]

    return asyncio.run(run())


def test_run_chatflow_persists_user_and_final_message():
    application_id = uuid4()
    run_id = uuid4()
    runner = _FakeRunner(
        run_id,
        "conv-1",
        application_id,
        output={"output": "最终回答"},
    )
    _, factory = _make_runner_factory(runner)
    service = _service(factory)
    prepared = _prepared(application_id)

    events = _collect(service, prepared)

    user_messages = [m for m in service._msg_repo.messages if m["role"] == "user"]
    assistant_messages = [m for m in service._msg_repo.messages if m["role"] == "assistant"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "你好"
    assert user_messages[0]["run_id"] == run_id
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "最终回答"
    assert assistant_messages[0]["run_id"] == run_id
    assert runner.ensure_inputs["USER_INPUT"] == "你好"
    assert service._conv_repo.touched == [prepared.conversation_id]
    assert service._uow.commits == 1
    assert [name for name, _ in events] == ["run_start", "result", "final"]


def test_run_chatflow_does_not_duplicate_emitted_output():
    application_id = uuid4()
    runner = _FakeRunner(
        uuid4(),
        "conv-1",
        application_id,
        output={"output": "最终回答"},
        emitted_text="最终回答",
    )
    _, factory = _make_runner_factory(runner)
    service = _service(factory)

    _collect(service, _prepared(application_id))

    assistant_messages = [m for m in service._msg_repo.messages if m["role"] == "assistant"]
    assert assistant_messages == []


def test_run_chatflow_resume_reuses_interrupted_run_and_persists_answer():
    application_id = uuid4()
    interrupted_run_id = uuid4()
    run_repo = _FakeRunRepo({interrupted_run_id})
    resume = {"answer": "选项 A"}
    runner = _FakeRunner(
        interrupted_run_id,
        "conv-1",
        application_id,
        output={"output": "续跑完成"},
    )
    seen, factory = _make_runner_factory(runner)
    service = _service(factory, run_repo)
    prepared = _prepared(application_id, message="", resume=resume)

    _collect(service, prepared)

    assert seen["run_id"] == interrupted_run_id
    assert runner.resumed == resume
    assert runner.ensure_inputs == {"resume": resume}
    user_messages = [m for m in service._msg_repo.messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "选项 A"
    assert user_messages[0]["run_id"] == interrupted_run_id


def test_run_chatflow_interrupt_persists_question_and_touches_conversation():
    application_id = uuid4()
    run_id = uuid4()
    runner = _FakeRunner(
        run_id,
        "conv-1",
        application_id,
        interrupt=GraphInterrupted(
            {"type": "question", "node_id": "q1", "question": "选哪个", "options": ["A"]},
            "conv-1",
        ),
    )
    _, factory = _make_runner_factory(runner)
    service = _service(factory)
    prepared = _prepared(application_id)

    events = _collect(service, prepared)

    assert "question" in [name for name, _ in events]
    question_messages = [
        m for m in service._msg_repo.messages if (m.get("metadata") or {}).get("type") == "question"
    ]
    assert len(question_messages) == 1
    assert question_messages[0]["content"] == "选哪个"
    assert question_messages[0]["run_id"] == run_id
    assert service._conv_repo.touched == [prepared.conversation_id]
    assert service._uow.commits == 1
