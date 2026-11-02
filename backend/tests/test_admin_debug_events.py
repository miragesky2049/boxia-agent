"""admin 画布试运行的中断事件契约：问答节点发 question，人审节点发 interrupted。"""

from __future__ import annotations

import asyncio
import json
import uuid

from internal.domain.graph.runtime import GraphInterrupted
from web.admin.routers.apps_admin import _push_interrupt


class _FakeRuntime:
    def __init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.conversation_id = uuid.uuid4()


def _drain(queue: asyncio.Queue) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    while not queue.empty():
        frame = queue.get_nowait()
        lines = [line for line in frame.splitlines() if line]
        event = lines[0].split("event:", 1)[1].strip()
        data = json.loads(lines[1].split("data:", 1)[1].strip())
        events.append((event, data))
    return events


def test_question_interrupt_emits_question_event():
    queue: asyncio.Queue = asyncio.Queue()
    runtime = _FakeRuntime()
    exc = GraphInterrupted(
        {
            "type": "question",
            "node_id": "n1",
            "node_title": "提问",
            "question": "选哪个？",
            "options": ["A", "B"],
        },
        "thread-1",
    )

    asyncio.run(_push_interrupt(queue, exc, runtime))

    events = _drain(queue)
    assert [name for name, _ in events] == ["question"]
    data = events[0][1]
    assert data["question"] == "选哪个？"
    assert data["options"] == ["A", "B"]
    assert data["thread_id"] == "thread-1"
    assert data["run_id"] == str(runtime.run_id)


def test_human_approval_interrupt_emits_interrupted_event():
    queue: asyncio.Queue = asyncio.Queue()
    runtime = _FakeRuntime()
    payload = {"type": "approval", "node_id": "n2", "assignee_role": "leader"}
    exc = GraphInterrupted(payload, "thread-2")

    asyncio.run(_push_interrupt(queue, exc, runtime))

    events = _drain(queue)
    assert [name for name, _ in events] == ["interrupted"]
    data = events[0][1]
    assert data["approval"] == payload
    assert data["thread_id"] == "thread-2"
