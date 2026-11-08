"""M4 PRD F14.9 接管路由态（T-c5，先测试后实现）。

覆盖出口条件全集：
- 路由：active NULL=归属应用应答（与基线逐字段一致）；active≠URL 应用→目标应答，
  run/assistant 消息归因目标、thread={cid}:{目标}（R22）；user 消息保持归属应用；
- 可见性拒绝：目标不可见→4xx 且原路由不动（不清 active）；
- resume 护栏（R21）：resume 不经 active 路由，审批快照按原 cid+thread 续跑，
  归属应用取自快照 run 行本身；
- handback:true：active 置 NULL、链清空、发 handoff 通告帧（returned=true）、不发 run；
- handoff 链纯函数：深度≤3（不含归属应用，对齐委派链预算）+ 去环；
- F14.11：通告文案 role=system 不入记忆窗口（normalize_history_rows 过滤锁定）；
- 迁移 0078 列与仓储读写（真实 Postgres）。

画布通道夹具复用 tests/test_chat_canvas_stream（同包内私有夹具导入）。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.application.apps.chat_service import ChatService
from internal.application.errors import NotFoundError, ValidationError
from internal.domain.agent.handoff import (
    MAX_HANDOFF_CHAIN_DEPTH,
    append_handoff_chain,
    handoff_chain_error,
    parse_handoff_chain,
)
from internal.domain.agent.memory import normalize_history_rows
from internal.infrastructure.model.database import get_engine
from internal.infrastructure.repository.apps.conversation_repository import ConversationRepository
from tests.test_chat_canvas_stream import _canvas_graph, _canvas_trace_events

_OWNER = uuid4()
_TARGET = uuid4()


# ---------------------------------------------------------------- 纯函数：链语义


def test_handoff_chain_rejects_loop() -> None:
    # A→B→A 乒乓：目标已在链中（含归属应用本身）即环，归位必须走 hand_back/handback
    assert "循环" in (
        handoff_chain_error([str(_OWNER), str(_TARGET)], str(_OWNER), str(_TARGET)) or ""
    )
    assert "循环" in (handoff_chain_error([str(_OWNER), "b"], "m", "b") or "")


def test_handoff_chain_depth_budget() -> None:
    # 归属应用不计入接管深度：owner+3 位专家合法，第 4 次接管拒绝
    chain3 = ["m", "b", "c", "d"]
    assert "深度" in (handoff_chain_error(chain3, "m", "e") or "")
    assert handoff_chain_error(["m", "b", "c"], "m", "d") is None
    assert MAX_HANDOFF_CHAIN_DEPTH == 3


def test_handoff_chain_parse_and_append() -> None:
    assert parse_handoff_chain(None) == []
    assert parse_handoff_chain("junk") == []
    assert parse_handoff_chain(["m", None, "", "b"]) == ["m", "b"]
    # 空链以归属应用为首种子；链存储顺序=接管顺序
    assert append_handoff_chain([], "m", "b") == ["m", "b"]
    assert append_handoff_chain(["m", "b"], "m", "c") == ["m", "b", "c"]


def test_normalize_history_rows_skips_handoff_notice_rows() -> None:
    # F14.11：handoff 通告文案 role=system，天然不入记忆窗口（本用例锁定）
    rows = [
        {"role": "user", "content": "问题"},
        {"role": "system", "content": "会话已交由专家接管"},
        {"role": "assistant", "content": "回答"},
        {"role": "system", "content": ""},
    ]
    assert normalize_history_rows(rows) == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
    ]


# ---------------------------------------------------------------- ChatService 夹具


class _Uow:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Principal:
    def __init__(self, tenant_id: UUID, user_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.username = "tester"


class _AppService:
    """多应用卡片视图：apps 缺键=不可见（assert 抛 NotFoundError，与真实口径一致）。"""

    def __init__(self, apps: dict[str, dict]) -> None:
        self._graph = _canvas_graph()
        self._apps = apps
        self.visibility_calls: list[str] = []
        self.graph_calls: list[str] = []

    def assert_user_can_view(self, application_id, tenant_id, user_id) -> dict:
        self.visibility_calls.append(str(application_id))
        card = self._apps.get(str(application_id))
        if card is None:
            raise NotFoundError("应用不存在或未开通")
        return card

    def get_visible_app_for_user(self, application_id, tenant_id, user_id) -> dict | None:
        return self._apps.get(str(application_id))

    async def get_runtime_graph(self, application_id, tenant_id) -> dict:
        self.graph_calls.append(str(application_id))
        return self._graph


class _ConvRepo:
    def __init__(self, conv: dict) -> None:
        self._conv = conv
        self.handoff_updates: list[dict] = []

    def get_conversation(self, conversation_id):
        if str(conversation_id) != str(self._conv["id"]):
            return None
        return dict(self._conv)

    def insert_conversation(self, **kwargs) -> UUID:
        return self._conv["id"]

    def touch(self, conversation_id) -> None:
        pass

    def list_conversations_by_user(self, **kwargs) -> list[dict]:
        return [dict(self._conv)]

    def update_handoff_state(
        self, conversation_id, *, active_application_id, handoff_chain
    ) -> None:
        self.handoff_updates.append(
            {
                "conversation_id": conversation_id,
                "active_application_id": active_application_id,
                "handoff_chain": handoff_chain,
            }
        )


class _MsgRepo:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []

    def append_message(self, **kwargs) -> int:
        self.appended.append(kwargs)
        return len(self.appended)

    def list_messages_by_conversation(self, conversation_id, *, limit: int = 50):
        return list(self.rows)


class _FakeRunRepo:
    """线程→run 行定位：direct 按 (app, thread) 精确匹配（基线），fallback 仅按线程。"""

    def __init__(self) -> None:
        self.by_thread: dict[str, dict] = {}
        self.direct_calls: list[tuple[str, str]] = []
        self.fallback_calls: list[str] = []

    def get_running_by_thread(self, tenant_id, workflow_id, thread_id):
        self.direct_calls.append((str(workflow_id), thread_id))
        row = self.by_thread.get(thread_id)
        if row and str(row["workflow_id"]) == str(workflow_id):
            return dict(row)
        return None

    def get_running_by_thread_any_app(self, tenant_id, thread_id):
        self.fallback_calls.append(thread_id)
        row = self.by_thread.get(thread_id)
        return dict(row) if row else None

    def update_run_status(self, run_id, **kwargs) -> None:
        pass


class _FakeRunner:
    def __init__(
        self,
        run_id,
        on_node_event,
        error: Exception | None = None,
        events: list[tuple[str, dict]] | None = None,
    ) -> None:
        self.run_id = run_id
        self._emit = on_node_event
        self._error = error
        self._events = events if events is not None else _canvas_trace_events()
        self.ensure_inputs: dict | None = None
        self.invoke_inputs: dict | None = None

    def ensure_run(self, input_data: dict) -> None:
        self.ensure_inputs = input_data

    async def invoke(self, input_data: dict) -> dict:
        self.invoke_inputs = input_data
        for event_type, payload in self._events:
            await self._emit(event_type, payload)
        if self._error is not None:
            raise self._error
        return {"output": "北京 20 度。"}

    async def purge_thread_checkpoints(self) -> None:
        pass


def _make_conv(*, active: UUID | None = None, chain: list[str] | None = None) -> dict:
    tenant_id, user_id = _tenant_user()
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "application_id": _OWNER,
        "active_application_id": active,
        "handoff_chain": chain or [],
    }


def _tenant_user() -> tuple[UUID, UUID]:
    return _TENANT, _USER


_TENANT = uuid4()
_USER = uuid4()


def _cards(**extra: dict) -> dict[str, dict]:
    apps = {
        str(_OWNER): {"id": str(_OWNER), "name": "主助手", "flow_type": "agent"},
        str(_TARGET): {"id": str(_TARGET), "name": "天气专家", "flow_type": "agent"},
    }
    apps.update({k: v for k, v in extra.items()})
    return apps


def _make_service(
    conv: dict,
    *,
    apps: dict[str, dict] | None = None,
    run_repo: Any | None = None,
    runner_error: Exception | None = None,
    runner_events: list[tuple[str, dict]] | None = None,
) -> tuple[ChatService, dict[str, Any]]:
    captured: dict[str, Any] = {"factory_kwargs": [], "runner": None}
    app_service = _AppService(apps if apps is not None else _cards())
    conv_repo = _ConvRepo(conv)
    msg_repo = _MsgRepo()
    uow = _Uow()
    principal = _Principal(_TENANT, _USER)
    if run_repo is None:
        run_repo = _FakeRunRepo()

    async def runner_factory(_app, _uow, _ctx, **kwargs):
        captured["factory_kwargs"].append(kwargs)
        runner = _FakeRunner(
            run_id=kwargs.get("run_id"),
            on_node_event=kwargs.get("on_node_event"),
            error=runner_error,
            events=runner_events,
        )
        captured["runner"] = runner
        return runner

    service = ChatService(
        uow,
        object(),
        principal,
        runner_factory,
        app_service=app_service,
        model_service=object(),
        resource_service=object(),
        conv_repo=conv_repo,
        msg_repo=msg_repo,
        run_repo=run_repo,
        default_llm_model_id="default-m",
        tool_executor_factory=lambda application_id, run_id: lambda name, args: "晴，20 度",
    )
    captured.update(
        app_service=app_service,
        conv_repo=conv_repo,
        msg_repo=msg_repo,
        uow=uow,
        run_repo=run_repo,
        principal=principal,
    )
    return service, captured


async def _collect(service: ChatService, application_id, query, cid, **kwargs):
    frames: list[tuple[str, dict]] = []
    async for name, payload in service.run_agent_stream(application_id, query, cid, None, **kwargs):
        frames.append((name, payload))
    return frames


# ---------------------------------------------------------------- 路由判定


def test_route_active_null_keeps_owner_app() -> None:
    conv = _make_conv()
    service, cap = _make_service(conv)
    routed = service.resolve_handoff_application(_OWNER, conversation_id=conv["id"], resume=None)
    assert routed == _OWNER
    # 目标应用没有被访问（无多余鉴权调用）
    assert cap["app_service"].visibility_calls == []


def test_route_active_overrides_to_target() -> None:
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv)
    routed = service.resolve_handoff_application(_OWNER, conversation_id=conv["id"], resume=None)
    assert routed == _TARGET
    assert str(_TARGET) in cap["app_service"].visibility_calls


def test_route_invisible_target_rejects_and_keeps_routing() -> None:
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    apps = {str(_OWNER): {"id": str(_OWNER), "name": "主助手", "flow_type": "agent"}}
    service, cap = _make_service(conv, apps=apps)
    with pytest.raises(NotFoundError):
        service.resolve_handoff_application(_OWNER, conversation_id=conv["id"], resume=None)
    # 拒绝且保持原路由：不得清 active
    assert cap["conv_repo"].handoff_updates == []


def test_route_resume_bypasses_routing() -> None:
    # R21：resume 一律按 URL 应用分派，active 即便指向他应用也不读会话行
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv)
    routed = service.resolve_handoff_application(
        _OWNER,
        conversation_id=conv["id"],
        resume={"approved": True},
    )
    assert routed == _OWNER


@pytest.mark.parametrize("conversation_id", [None])
def test_route_without_conversation_or_foreign_conversation(conversation_id) -> None:
    conv = _make_conv(active=_TARGET)
    service, _ = _make_service(conv)
    assert (
        service.resolve_handoff_application(
            _OWNER,
            conversation_id=conversation_id,
            resume=None,
        )
        == _OWNER
    )
    # 会话不属于当前用户/URL 应用：不路由，交下游按基线报"会话不存在或无权访问"
    foreign = _make_conv()
    foreign["user_id"] = uuid4()
    service2, _ = _make_service(foreign)
    assert (
        service2.resolve_handoff_application(
            _OWNER,
            conversation_id=foreign["id"],
            resume=None,
        )
        == _OWNER
    )


# ---------------------------------------------------------------- 接管轮执行归因


def test_takeover_round_attributes_target() -> None:
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv)
    frames = asyncio.run(
        _collect(
            service,
            _OWNER,
            "北京天气",
            conv["id"],
            route_application_id=_TARGET,
        )
    )
    names = [name for name, _ in frames]
    assert names[0] == "run_start" and names[-2] == "result"
    result = frames[-2][1]
    assert result["agent_id"] == str(_TARGET)

    # 图与运行归因目标应用
    assert cap["app_service"].graph_calls == [str(_TARGET)]
    factory_kwargs = cap["factory_kwargs"][0]
    assert factory_kwargs["application_id"] == _TARGET
    # R22：接管轮线程 = {cid}:{目标}，防跨应用 checkpoint 叠套
    assert factory_kwargs["thread_id"] == f"{conv['id']}:{_TARGET}"

    appended = cap["msg_repo"].appended
    user_rows = [m for m in appended if m["role"] == "user"]
    assistant_rows = [m for m in appended if m["role"] == "assistant"]
    assert all(m["application_id"] == _OWNER for m in user_rows)
    assert all(m["application_id"] == _TARGET for m in assistant_rows)


def test_active_null_stream_matches_baseline() -> None:
    conv = _make_conv()
    service, cap = _make_service(conv)
    frames = asyncio.run(_collect(service, _OWNER, "北京天气", conv["id"]))
    names = [name for name, _ in frames]
    assert names == [
        "run_start",
        "llm_start",
        "llm_end",
        "tool_start",
        "tool_end",
        "llm_start",
        "llm_end",
        "result",
        "final",
    ]
    assert frames[-2][1]["agent_id"] == str(_OWNER)
    factory_kwargs = cap["factory_kwargs"][0]
    assert factory_kwargs["application_id"] == _OWNER
    # 无接管：线程保持会话 ID，不轮转、不加后缀
    assert factory_kwargs["thread_id"] == str(conv["id"])
    for row in cap["msg_repo"].appended:
        assert row["application_id"] == _OWNER


def test_takeover_thread_ignores_client_thread_id() -> None:
    # R22：接管轮强制 {cid}:{目标}，客户端携带旧 thread_id 不能穿透隔离
    conv = _make_conv(active=_TARGET)
    service, cap = _make_service(conv)
    asyncio.run(
        _collect(
            service,
            _OWNER,
            "北京天气",
            conv["id"],
            route_application_id=_TARGET,
            thread_id=f"{conv['id']}:spoof",
        )
    )
    assert cap["factory_kwargs"][0]["thread_id"] == f"{conv['id']}:{_TARGET}"


def test_takeover_round_failure_leaves_routing_untouched() -> None:
    # R21 断连一致性：接管轮执行失败（run 未成功提交）→ 路由态不得有任何写入，
    # active 切换本就只发生在成功提交后（T-c7），失败轮必须零副作用
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv, runner_error=RuntimeError("图执行失败"))
    frames = asyncio.run(
        _collect(
            service,
            _OWNER,
            "北京天气",
            conv["id"],
            route_application_id=_TARGET,
        )
    )
    names = [name for name, _ in frames]
    assert names[-2:] == ["error", "final"]
    assert cap["conv_repo"].handoff_updates == []


# ---------------------------------------------------------------- resume 护栏


def _pending_run_row(thread: str, app_id: UUID) -> dict:
    return {
        "id": uuid4(),
        "workflow_id": app_id,
        "execute_status": "interrupted",
        "interrupt_payload": {"type": "tool_approval", "snapshot": {"round": 1}},
    }


def test_resume_locates_snapshot_by_thread_not_active() -> None:
    # R21：审批快照 run 属于接管应用 B；resume 不读 active（active 甚至指向 C），
    # 按原 thread 二次定位后在快照自己的应用上续跑
    conv = _make_conv(active=uuid4())
    run_repo = _FakeRunRepo()
    thread = f"{conv['id']}:{_TARGET}"
    run_repo.by_thread[thread] = _pending_run_row(thread, _TARGET)
    service, cap = _make_service(conv, run_repo=run_repo)

    frames = asyncio.run(
        _collect(
            service,
            _OWNER,
            "",
            conv["id"],
            resume={"approved": True},
            thread_id=thread,
        )
    )
    assert [name for name, _ in frames][-2] == "result"
    # 直接定位（归属应用）未命中后才允许按线程兜底，且兜底不再换 thread
    assert run_repo.direct_calls and run_repo.fallback_calls == [thread]
    assert cap["app_service"].graph_calls == [str(_TARGET)]
    assert cap["factory_kwargs"][0]["thread_id"] == thread


def test_resume_same_app_pending_skips_fallback() -> None:
    # 基线：快照 run 就在归属应用线程上 → 直接命中，不触发 any_app 兜底
    conv = _make_conv()
    run_repo = _FakeRunRepo()
    run_repo.by_thread[str(conv["id"])] = _pending_run_row(str(conv["id"]), _OWNER)
    service, cap = _make_service(conv, run_repo=run_repo)
    frames = asyncio.run(
        _collect(
            service,
            _OWNER,
            "",
            conv["id"],
            resume={"approved": True},
        )
    )
    assert [name for name, _ in frames][-2] == "result"
    assert run_repo.fallback_calls == []
    assert cap["app_service"].graph_calls == [str(_OWNER)]


def test_resume_without_pending_rejects_validation_error() -> None:
    # 无快照可续：预检异常上抛（HTTP 层 _sse_response 统一转 error+final 帧）
    conv = _make_conv()
    service, _ = _make_service(conv, run_repo=_FakeRunRepo())
    with pytest.raises(ValidationError, match="没有待恢复的工具审批"):
        asyncio.run(
            _collect(
                service,
                _OWNER,
                "",
                conv["id"],
                resume={"approved": True},
            )
        )


# ---------------------------------------------------------------- handback


def test_prepare_chat_run_handback_skips_message_check() -> None:
    service, _ = _make_service(_make_conv(active=_TARGET))
    # 空 message + handback：归位请求不要求正文
    service.prepare_chat_run(
        _OWNER,
        message="",
        conversation_id=_make_conv()["id"],
        resume=None,
        handback=True,
    )
    with pytest.raises(ValidationError):
        service.prepare_chat_run(
            _OWNER,
            message="",
            conversation_id=None,
            resume=None,
            handback=True,
        )


def test_prepare_handback_validation() -> None:
    conv = _make_conv(active=_TARGET)
    service, _ = _make_service(conv)
    ctx = service.prepare_handback(_OWNER, conv["id"])
    assert str(ctx["active_application_id"]) == str(_TARGET)
    assert ctx["owner_name"] == "主助手"

    # 无接管中的会话：拒绝
    plain = _make_conv()
    service2, _ = _make_service(plain)
    with pytest.raises(ValidationError):
        service2.prepare_handback(_OWNER, plain["id"])

    # 会话不属于该用户：NotFound（与 _resolve_chat_conversation 同口径）
    foreign = _make_conv(active=_TARGET)
    foreign["user_id"] = uuid4()
    service3, _ = _make_service(foreign)
    with pytest.raises(NotFoundError):
        service3.prepare_handback(_OWNER, foreign["id"])


def test_handback_stream_clears_routing_and_emits_notice_frame() -> None:
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv)
    ctx = service.prepare_handback(_OWNER, conv["id"])

    async def _drain():
        out = []
        async for name, payload in service.run_handback_stream(_OWNER, conv["id"], ctx):
            out.append((name, payload))
        return out

    frames = asyncio.run(_drain())
    assert [name for name, _ in frames] == ["handoff", "final"]
    assert frames[0][1] == {
        "from_app_id": str(_TARGET),
        "to_app_id": str(_OWNER),
        "display_name": "主助手",
        "returned": True,
    }
    update = cap["conv_repo"].handoff_updates[0]
    assert update["conversation_id"] == conv["id"]
    assert update["active_application_id"] is None
    assert update["handoff_chain"] == []
    # 通告文案 role=system（不入记忆窗口，前端历史回放可见）
    sys_rows = [m for m in cap["msg_repo"].appended if m["role"] == "system"]
    assert sys_rows and sys_rows[0]["application_id"] == _OWNER
    assert "主助手" in sys_rows[0]["content"]
    # T-c8：metadata.kind 定名 handoff_notice，list_messages 仅放行该形态 system 行
    assert sys_rows[0]["metadata"] == {"kind": "handoff_notice"}
    assert cap["uow"].commits == 1
    # 不发 run：未触达 runner 工厂与图
    assert cap["factory_kwargs"] == []
    assert cap["app_service"].graph_calls == []


# ---------------------------------------------------------------- 会话列表透出


def test_list_conversations_exposes_active_application_additively() -> None:
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, _ = _make_service(conv)
    rows = asyncio.run(service.list_conversations(_OWNER))
    assert rows[0]["active_application_id"] == str(_TARGET)
    assert rows[0]["active_application"] == "天气专家"

    plain = _make_conv()
    service2, _ = _make_service(plain)
    baseline_rows = asyncio.run(service2.list_conversations(_OWNER))
    # active NULL：不出新键，基线响应逐字段一致
    assert "active_application_id" not in baseline_rows[0]
    assert "active_application" not in baseline_rows[0]


# ---------------------------------------------------------------- 内核 handoff 输出收口（T-c7）


def _handoff_kernel_events(*, application_id: str | None, returned: bool) -> list[tuple[str, dict]]:
    """构造与 agent_loop 节点 F14.9 出口一致的画布 trace：接管轮正文外发、
    outputs.handoff 透出、finish_reason 覆盖。"""
    tool_name = "hand_back" if returned else "agent_expert"
    finish = "handed_back" if returned else "handed_off"
    handoff = {
        "tool_name": tool_name,
        "tool_call_id": "c1",
        "arguments_raw": "{}",
        "iteration": 1,
        "tool_round": 0,
        "application_id": application_id,
        "returned": returned,
    }
    return [
        ("node_start", {"node_id": "loop_x", "node_type": "100", "inputs": {}}),
        (
            "prompt_text",
            {
                "phase": "execute",
                "iteration": 1,
                "tool_round": 0,
                "role": "assistant",
                "content": "好的，转到专家处理。",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                "finish_reason": "tool_calls",
                "tool_calls": [{"id": "c1", "name": tool_name, "arguments": "{}"}],
            },
        ),
        ("tool_handoff", {"phase": "execute", "reflect_round": 0, **handoff}),
        (
            "node_end",
            {
                "node_id": "loop_x",
                "status": "success",
                "outputs": {
                    "output": "",
                    "plan": [],
                    "model": "m1",
                    "finish_reason": finish,
                    "handoff": handoff,
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                },
            },
        ),
    ]


def test_kernel_handoff_switches_routing_and_emits_frame() -> None:
    """归属应用应答轮命中接管：链校验+可见性通过 → active=目标、链追加归属首元素，
    handoff 帧先于 result；本轮应答仍归归属应用（切换自下一轮生效）。"""
    conv = _make_conv()
    service, cap = _make_service(
        conv,
        runner_events=_handoff_kernel_events(application_id=str(_TARGET), returned=False),
    )
    frames = asyncio.run(_collect(service, _OWNER, "帮我查天气趋势", conv["id"]))
    names = [name for name, _ in frames]
    assert names[-3:] == ["handoff", "result", "final"]
    assert frames[-3][1] == {
        "from_app_id": str(_OWNER),
        "to_app_id": str(_TARGET),
        "display_name": "天气专家",
        "returned": False,
    }
    result = frames[-2][1]
    assert result["content"] == ""
    assert result["finish_reason"] == "handed_off"
    assert result["agent_id"] == str(_OWNER)
    assert cap["conv_repo"].handoff_updates == [
        {
            "conversation_id": conv["id"],
            "active_application_id": _TARGET,
            "handoff_chain": [str(_OWNER), str(_TARGET)],
        }
    ]
    assistant_rows = [m for m in cap["msg_repo"].appended if m["role"] == "assistant"]
    assert len(assistant_rows) == 1
    assert assistant_rows[0]["content"] == "" and assistant_rows[0]["application_id"] == _OWNER
    assert cap["uow"].commits == 1
    # T-c8：接管轮同事务落 system 通告行（历史回放与 live 帧文案一致）
    sys_rows = [m for m in cap["msg_repo"].appended if m["role"] == "system"]
    assert len(sys_rows) == 1
    assert sys_rows[0]["content"] == "会话已移交给专家「天气专家」，后续对话由其应答。"


def test_kernel_handoff_frames_emitted_after_commit() -> None:
    """批末 review #1：handoff/result 帧必须在 DB 提交后才发出（对齐审批挂起现场
    "先提交后发帧"先例）——客户端收到帧即同步会话摘要时，绝不能读到未提交的旧路由态。"""
    conv = _make_conv()
    service, cap = _make_service(
        conv, runner_events=_handoff_kernel_events(application_id=str(_TARGET), returned=False)
    )

    async def _walk() -> list[str]:
        seen: list[str] = []
        async for name, _payload in service.run_agent_stream(
            _OWNER, "帮我查天气趋势", conv["id"], None
        ):
            if name in ("handoff", "result"):
                assert cap["uow"].commits >= 1, f"{name} 帧先于提交发出"
                seen.append(name)
        return seen

    assert asyncio.run(_walk()) == ["handoff", "result"]


def test_kernel_hand_back_clears_routing_on_takeover_round() -> None:
    """接管轮（携带 handoff_inbound）命中 hand_back：清空路由态，
    归位帧 to=归属应用、display_name=归属应用名。"""
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(
        conv,
        runner_events=_handoff_kernel_events(application_id=None, returned=True),
    )
    frames = asyncio.run(
        _collect(service, _OWNER, "已办结", conv["id"], route_application_id=_TARGET)
    )
    names = [name for name, _ in frames]
    assert names[-3:] == ["handoff", "result", "final"]
    assert frames[-3][1] == {
        "from_app_id": str(_TARGET),
        "to_app_id": str(_OWNER),
        "display_name": "主助手",
        "returned": True,
    }
    assert cap["conv_repo"].handoff_updates == [
        {
            "conversation_id": conv["id"],
            "active_application_id": None,
            "handoff_chain": [],
        }
    ]
    assert cap["runner"].invoke_inputs["handoff_inbound"] == {"from_application_id": str(_OWNER)}
    assert frames[-2][1]["finish_reason"] == "handed_back"
    assert cap["uow"].commits == 1
    # T-c8：内核归位同样落 system 通告行，文案与 handback 端点一致
    sys_rows = [m for m in cap["msg_repo"].appended if m["role"] == "system"]
    assert len(sys_rows) == 1
    assert sys_rows[0]["content"] == "接管已结束，会话已归位主助手「主助手」。"
    assert sys_rows[0]["metadata"] == {"kind": "handoff_notice"}


def test_kernel_hand_back_without_inbound_rejected() -> None:
    """非接管轮出现 returned=true 输出（脏配置伪造）：拒绝且不触碰路由。"""
    conv = _make_conv()
    service, cap = _make_service(
        conv,
        runner_events=_handoff_kernel_events(application_id=None, returned=True),
    )
    frames = asyncio.run(_collect(service, _OWNER, "q", conv["id"]))
    names = [name for name, _ in frames]
    assert names[-2:] == ["error", "final"]
    assert "不在接管中" in frames[-2][1]["message"]
    assert cap["conv_repo"].handoff_updates == []
    assert cap["uow"].commits == 0
    assert not [m for m in cap["msg_repo"].appended if m["role"] == "system"]


def test_kernel_handoff_cycle_rejected_without_state_change() -> None:
    """链内去环（乒乓）：error 帧收口，路由态与落库零触碰（切换仅在 run 成功出口）。"""
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(
        conv,
        runner_events=_handoff_kernel_events(application_id=str(_OWNER), returned=False),
    )
    frames = asyncio.run(
        _collect(service, _OWNER, "转回主助手", conv["id"], route_application_id=_TARGET)
    )
    names = [name for name, _ in frames]
    assert names[-2:] == ["error", "final"]
    assert "接管循环" in frames[-2][1]["message"]
    assert "handoff" not in names and "result" not in names
    assert cap["conv_repo"].handoff_updates == []
    assert not [m for m in cap["msg_repo"].appended if m["role"] == "system"]


def test_kernel_handoff_depth_rejected() -> None:
    """深度预算（归属不计入，最多 3 位应答应用）：第 4 次接管拒绝。"""
    c, d, e = uuid4(), uuid4(), uuid4()
    extra = {str(x): {"id": str(x), "name": f"专家{x}", "flow_type": "agent"} for x in (c, d, e)}
    apps = _cards()
    apps.update(extra)
    conv = _make_conv(active=d, chain=[str(_OWNER), str(_TARGET), str(c), str(d)])
    service, cap = _make_service(
        conv,
        apps=apps,
        runner_events=_handoff_kernel_events(application_id=str(e), returned=False),
    )
    frames = asyncio.run(_collect(service, _OWNER, "再转一位", conv["id"], route_application_id=d))
    names = [name for name, _ in frames]
    assert names[-2:] == ["error", "final"]
    assert "深度" in frames[-2][1]["message"]
    assert cap["conv_repo"].handoff_updates == []


def test_kernel_handoff_invisible_target_rejected() -> None:
    """应答中途目标应用不可见（配置保存后被下架）：可见性兜底拒绝，原路由不动。"""
    ghost = uuid4()
    conv = _make_conv()
    service, cap = _make_service(
        conv,
        runner_events=_handoff_kernel_events(application_id=str(ghost), returned=False),
    )
    frames = asyncio.run(_collect(service, _OWNER, "q", conv["id"]))
    names = [name for name, _ in frames]
    assert names[-2:] == ["error", "final"]
    assert "应用不存在或未开通" in frames[-2][1]["message"]
    assert cap["conv_repo"].handoff_updates == []


def test_takeover_round_without_handoff_output_matches_baseline() -> None:
    """接管轮正常收敛（未调 hand_back）：无 handoff 帧、路由零更新；
    仅接管轮携带 handoff_inbound，归属轮不携带（基线 start_inputs 不变）。"""
    conv = _make_conv(active=_TARGET, chain=[str(_OWNER), str(_TARGET)])
    service, cap = _make_service(conv)
    frames = asyncio.run(
        _collect(service, _OWNER, "明天穿什么", conv["id"], route_application_id=_TARGET)
    )
    names = [name for name, _ in frames]
    assert "handoff" not in names
    assert names[-2:] == ["result", "final"]
    assert cap["conv_repo"].handoff_updates == []
    assert cap["runner"].invoke_inputs["handoff_inbound"] == {"from_application_id": str(_OWNER)}

    service2, cap2 = _make_service(_make_conv())
    frames2 = asyncio.run(_collect(service2, _OWNER, "q", cap2["conv_repo"]._conv["id"]))
    assert "handoff" not in [name for name, _ in frames2]
    assert "handoff_inbound" not in cap2["runner"].invoke_inputs


def test_list_messages_replays_handoff_notice_and_app_attribution() -> None:
    """T-c8 历史回放：system 通告行仅放行 kind=handoff_notice 形态；每行透传
    application_id（前端徽标判定 message 归属 ≠ 会话归属应用）。"""
    conv = _make_conv()
    service, cap = _make_service(conv)
    cap["msg_repo"].rows = [
        {
            "id": uuid4(),
            "role": "user",
            "content": "帮我查天气",
            "application_id": _OWNER,
            "tool_calls": None,
            "created_at": None,
            "metadata": None,
        },
        {
            "id": uuid4(),
            "role": "system",
            "content": "会话已移交给专家「天气专家」，后续对话由其应答。",
            "application_id": _OWNER,
            "tool_calls": None,
            "created_at": None,
            "metadata": {"kind": "handoff_notice"},
        },
        {
            "id": uuid4(),
            "role": "assistant",
            "content": "明天晴，20 度。",
            "application_id": _TARGET,
            "tool_calls": None,
            "created_at": None,
            "metadata": None,
        },
        {
            "id": uuid4(),
            "role": "system",
            "content": "非接管类系统行不透出",
            "application_id": _OWNER,
            "tool_calls": None,
            "created_at": None,
            "metadata": None,
        },
    ]
    rows = asyncio.run(service.list_messages(_OWNER, conv["id"]))
    assert [r["role"] for r in rows] == ["user", "system", "assistant"]
    assert rows[1]["kind"] == "handoff_notice"
    assert rows[1]["content"] == "会话已移交给专家「天气专家」，后续对话由其应答。"
    # 应答徽标数据源：专家轮 assistant 行归因目标应用
    assert rows[0]["application_id"] == str(_OWNER)
    assert rows[2]["application_id"] == str(_TARGET)


def test_list_messages_baseline_rows_unchanged_when_no_handoff() -> None:
    """无接管会话：基线行仅追加 application_id 键，行数/顺序/其余键不动。"""
    conv = _make_conv()
    service, cap = _make_service(conv)
    cap["msg_repo"].rows = [
        {
            "id": uuid4(),
            "role": "user",
            "content": "你好",
            "application_id": _OWNER,
            "tool_calls": None,
            "created_at": None,
            "metadata": None,
        },
        {
            "id": uuid4(),
            "role": "assistant",
            "content": "你好，有什么可以帮你",
            "application_id": _OWNER,
            "tool_calls": None,
            "created_at": None,
            "metadata": None,
        },
    ]
    rows = asyncio.run(service.list_messages(_OWNER, conv["id"]))
    assert len(rows) == 2
    assert rows[0]["application_id"] == str(_OWNER)
    assert set(rows[0]) == {
        "message_id",
        "role",
        "content",
        "tool_calls",
        "created_at",
        "application_id",
    }


# ---------------------------------------------------------------- 集成：迁移 0078


API = "/api/v1/user"
ADMIN_APPS = "/api/v1/admin/apps"


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_agent_app(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post(
        ADMIN_APPS,
        json={"name": name, "description": "0078 测试", "flow_type": "agent"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    app_id = resp.json()["application_id"]
    assert (
        client.post(
            f"{ADMIN_APPS}/{app_id}/listing", json={"listed": True}, headers=headers
        ).status_code
        == 200
    )
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE application SET sale_mode = 2 WHERE id = :aid"), {"aid": app_id})
    return app_id


def test_conversation_handoff_columns_roundtrip(client: TestClient, tenant_client) -> None:
    """真实 Postgres：0078 列默认值、仓储写读、链 JSONB 原样往返。"""
    from tests.helpers import (
        create_tenant,
        create_user,
        list_roles,
        tenant_admin_client,
    )

    platform = _platform_headers(client)
    owner_id = UUID(_create_agent_app(client, platform, "接管归属方"))
    target_id = UUID(_create_agent_app(client, platform, "接管目标方"))

    create_tenant(client, platform, code="hotrf", name="接管回环公司")
    admin_site, admin_headers, _ = tenant_admin_client(tenant_client, "hotrf")
    viewer_role_id = list_roles(admin_site, admin_headers)["viewer"]["id"]
    create_user(admin_site, admin_headers, username="ho-user", role_id=viewer_role_id)
    with get_engine().begin() as conn:
        tenant_id = conn.execute(text("SELECT id FROM tenants WHERE code = 'hotrf'")).scalar_one()
        user_id = conn.execute(text("SELECT id FROM users WHERE username = 'ho-user'")).scalar_one()

    from sqlalchemy.orm import Session

    with Session(get_engine()) as session:
        repo = ConversationRepository(session)
        cid = repo.insert_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=owner_id,
            title="接管测试",
        )
        row = repo.get_conversation(cid)
        assert row["active_application_id"] is None
        assert row["handoff_chain"] == []

        repo.update_handoff_state(
            cid,
            active_application_id=target_id,
            handoff_chain=[str(owner_id), str(target_id)],
        )
        session.commit()
        row = repo.get_conversation(cid)
        assert row["active_application_id"] == target_id
        assert row["handoff_chain"] == [str(owner_id), str(target_id)]

        repo.update_handoff_state(cid, active_application_id=None, handoff_chain=[])
        session.commit()
        row = repo.get_conversation(cid)
        assert row["active_application_id"] is None
        assert row["handoff_chain"] == []

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM conversation WHERE id = :cid"), {"cid": cid})


def _hot_user_client(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
    owner_id: str,
    target_id: str,
    *,
    subscribe_target: bool,
):
    """租户订阅 owner（可选 target）并登录用户端，返回 (site, headers, tenant_id, user_id)。"""
    from tests.helpers import (
        USER_PASSWORD,
        create_tenant,
        create_user,
        list_roles,
        tenant_admin_client,
    )

    platform = _platform_headers(client)
    create_tenant(client, platform, code="hosite", name="接管入口公司")
    admin_site, admin_headers, _ = tenant_admin_client(tenant_client, "hosite")
    for app_id in [owner_id] + ([target_id] if subscribe_target else []):
        assert (
            admin_site.post(
                "/api/v1/admin/marketplace/subscribe",
                json={"application_id": app_id},
                headers=admin_headers,
            ).status_code
            == 200
        )
    viewer_role_id = list_roles(admin_site, admin_headers)["viewer"]["id"]
    create_user(admin_site, admin_headers, username="ho-site-user", role_id=viewer_role_id)
    site = persistent_user_tenant_client("hosite")
    login = site.post(
        "/api/v1/user/auth/login",
        json={"username": "ho-site-user", "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    with get_engine().begin() as conn:
        tenant_id = conn.execute(text("SELECT id FROM tenants WHERE code = 'hosite'")).scalar_one()
        user_id = conn.execute(
            text("SELECT id FROM users WHERE username = 'ho-site-user'")
        ).scalar_one()
    return site, headers, tenant_id, user_id


def test_handback_endpoint_flow(
    client: TestClient, tenant_client, persistent_user_tenant_client
) -> None:
    """HTTP 层：接管中会话 handback:true → 200 SSE 仅 handoff(returned)+final，DB 已归位。"""
    from sqlalchemy.orm import Session

    platform = _platform_headers(client)
    owner_id = _create_agent_app(client, platform, "归位归属方")
    target_id = _create_agent_app(client, platform, "归位目标方")
    site, headers, tenant_id, user_id = _hot_user_client(
        client,
        tenant_client,
        persistent_user_tenant_client,
        owner_id,
        target_id,
        subscribe_target=True,
    )
    with Session(get_engine()) as session:
        repo = ConversationRepository(session)
        cid = repo.insert_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=UUID(owner_id),
            title="接管中",
        )
        repo.update_handoff_state(
            cid,
            active_application_id=UUID(target_id),
            handoff_chain=[owner_id, target_id],
        )
        session.commit()

        resp = site.post(
            f"{API}/agents/{owner_id}/chatflow/run/stream",
            json={"conversation_id": str(cid), "handback": True},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "event: handoff" in body and '"returned":true' in body
        assert "run_start" not in body
        row = repo.get_conversation(cid)
        assert row["active_application_id"] is None and row["handoff_chain"] == []
        messages = [
            r._mapping
            for r in session.execute(
                text("SELECT role, content FROM message WHERE conversation_id = :cid"),
                {"cid": cid},
            )
        ]
        assert any(m["role"] == "system" and "归位" in m["content"] for m in messages)
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM conversation WHERE id = :cid"), {"cid": cid})


def test_takeover_routing_invisible_target_rejected_before_sse(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    """HTTP 层：active 指向未订阅应用 → 消息请求在 SSE 之前 4xx，active 保持不动。"""
    from sqlalchemy.orm import Session

    platform = _platform_headers(client)
    owner_id = _create_agent_app(client, platform, "隐身路由方")
    target_id = _create_agent_app(client, platform, "隐身目标方")
    site, headers, tenant_id, user_id = _hot_user_client(
        client,
        tenant_client,
        persistent_user_tenant_client,
        owner_id,
        target_id,
        subscribe_target=False,
    )
    with Session(get_engine()) as session:
        repo = ConversationRepository(session)
        cid = repo.insert_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=UUID(owner_id),
            title="隐身接管",
        )
        repo.update_handoff_state(
            cid,
            active_application_id=UUID(target_id),
            handoff_chain=[owner_id, target_id],
        )
        session.commit()

        resp = site.post(
            f"{API}/agents/{owner_id}/chatflow/run/stream",
            json={"conversation_id": str(cid), "message": "你好"},
            headers=headers,
        )
        assert resp.status_code in (404, 422), resp.text
        assert "text/event-stream" not in resp.headers.get("content-type", "")
        row = repo.get_conversation(cid)
        # 拒绝但保持原路由：active 不被清理
        assert row["active_application_id"] == UUID(target_id)
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM conversation WHERE id = :cid"), {"cid": cid})
