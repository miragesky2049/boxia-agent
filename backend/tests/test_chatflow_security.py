"""对话流入口安全校验：应用类型、thread_id 归属。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from internal.application.apps.chat_service import ChatService
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.graph.runtime import GraphRuntime


def _service(tenant_id=None) -> ChatService:
    service = object.__new__(ChatService)
    service._tenant_id = tenant_id or uuid4()
    service._user_id = uuid4()
    return service


def test_bind_thread_defaults_to_conversation_id():
    service = _service()
    cid = uuid4()
    assert service._bind_chatflow_thread_id(cid, None) == str(cid)
    assert service._bind_chatflow_thread_id(cid, "  ") == str(cid)


def test_bind_thread_accepts_conversation_and_sub_thread():
    service = _service()
    cid = uuid4()
    assert service._bind_chatflow_thread_id(cid, str(cid)) == str(cid)
    assert service._bind_chatflow_thread_id(cid, f"{cid}:branch-1") == f"{cid}:branch-1"


def test_bind_thread_accepts_current_tenant_prefix():
    service = _service()
    cid = uuid4()
    raw = f"{service._tenant_id}:{cid}"
    assert service._bind_chatflow_thread_id(cid, raw) == str(cid)


def test_bind_thread_rejects_other_conversation():
    service = _service()
    with pytest.raises(ForbiddenError):
        service._bind_chatflow_thread_id(uuid4(), str(uuid4()))


def test_bind_thread_rejects_other_tenant():
    service = _service()
    cid = uuid4()
    with pytest.raises(ForbiddenError):
        service._bind_chatflow_thread_id(cid, f"{uuid4()}:{cid}")


class _FakeAppService:
    def __init__(self, flow_type: str) -> None:
        self.flow_type = flow_type

    def assert_user_can_view(self, *args, **kwargs):
        return {"id": str(args[0]), "flow_type": self.flow_type}


def test_assert_chatflow_application_accepts_chatflow():
    service = _service()
    service._app_service = _FakeAppService("chatflow")
    card = service.assert_chatflow_application(uuid4())
    assert card["flow_type"] == "chatflow"


def test_assert_chatflow_application_rejects_workflow():
    service = _service()
    service._app_service = _FakeAppService("workflow")
    with pytest.raises(ValidationError):
        service.assert_chatflow_application(uuid4())


class _FakeConvRepo:
    def __init__(self, conv: dict | None = None) -> None:
        self.conv = conv
        self.inserted: list[dict] = []

    def get_conversation(self, conversation_id):
        return self.conv

    def insert_conversation(self, **kwargs):
        self.inserted.append(kwargs)
        return uuid4()


def _prepare_service(conv: dict | None = None, flow_type: str = "chatflow"):
    service = _service()
    service._app_service = _FakeAppService(flow_type)
    service._conv_repo = _FakeConvRepo(conv)
    return service


def _conv(service: ChatService, application_id, **overrides) -> dict:
    data = {
        "id": uuid4(),
        "user_id": service._user_id,
        "application_id": application_id,
        "tenant_id": service._tenant_id,
        "title": "历史会话",
    }
    data.update(overrides)
    return data


def test_prepare_chatflow_run_rejects_workflow_application():
    service = _prepare_service(flow_type="workflow")
    with pytest.raises(ValidationError):
        service.prepare_chatflow_run(
            uuid4(),
            message="hi",
            conversation_id=None,
            resume=None,
            thread_id=None,
        )


def test_prepare_chatflow_run_requires_message_or_resume():
    service = _prepare_service()
    with pytest.raises(ValidationError):
        service.prepare_chatflow_run(
            uuid4(),
            message="   ",
            conversation_id=None,
            resume=None,
            thread_id=None,
        )


def test_prepare_chatflow_run_requires_conversation_for_resume():
    service = _prepare_service()
    with pytest.raises(ValidationError):
        service.prepare_chatflow_run(
            uuid4(),
            message="",
            conversation_id=None,
            resume={"answer": "A"},
            thread_id=None,
        )


def test_prepare_chatflow_run_rejects_foreign_conversation():
    application_id = uuid4()
    service = _prepare_service()
    conv = _conv(service, application_id, user_id=uuid4())
    service._conv_repo.conv = conv
    with pytest.raises(NotFoundError):
        service.prepare_chatflow_run(
            application_id,
            message="hi",
            conversation_id=conv["id"],
            resume=None,
            thread_id=None,
        )


def test_prepare_chatflow_run_rejects_forged_thread():
    application_id = uuid4()
    service = _prepare_service()
    conv = _conv(service, application_id)
    service._conv_repo.conv = conv
    with pytest.raises(ForbiddenError):
        service.prepare_chatflow_run(
            application_id,
            message="hi",
            conversation_id=conv["id"],
            resume=None,
            thread_id=str(uuid4()),
        )


def test_prepare_chatflow_run_creates_conversation_and_binds_thread():
    application_id = uuid4()
    service = _prepare_service()
    prepared = service.prepare_chatflow_run(
        application_id,
        message="  帮我写个总结  ",
        conversation_id=None,
        resume=None,
        thread_id=None,
    )

    assert prepared.message == "帮我写个总结"
    assert prepared.conversation_title == "帮我写个总结"
    assert prepared.thread_id == str(prepared.conversation_id)
    assert service._conv_repo.inserted[0]["application_id"] == application_id
    assert service._conv_repo.inserted[0]["title"] == "帮我写个总结"


def test_prepare_chatflow_run_accepts_existing_conversation_sub_thread():
    application_id = uuid4()
    service = _prepare_service()
    conv = _conv(service, application_id)
    service._conv_repo.conv = conv
    sub_thread = f"{conv['id']}:branch-1"

    prepared = service.prepare_chatflow_run(
        application_id,
        message="继续",
        conversation_id=conv["id"],
        resume=None,
        thread_id=sub_thread,
    )

    assert prepared.thread_id == sub_thread
    assert prepared.conversation_title == "历史会话"


def test_runtime_strips_only_current_tenant_prefix():
    tenant_id = uuid4()
    runtime = GraphRuntime({}, tenant_id=tenant_id, thread_id=f"{tenant_id}:conv-1")
    assert runtime.thread_id == "conv-1"

    foreign = GraphRuntime({}, tenant_id=tenant_id, thread_id="conv-1:branch")
    assert foreign.thread_id == "conv-1:branch"
