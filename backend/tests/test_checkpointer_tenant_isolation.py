"""A13：Checkpointer 多租户隔离单测。

验证：
1. 同一业务 thread_id 在不同租户下落到不同 checkpoint key（前缀隔离）。
2. GraphRuntime 构造时若传入带"别的租户前缀"的 thread_id，直接拒绝。
3. 传入带"自己租户前缀"的 thread_id 能正确剥前缀，等价于裸 thread_id。
4. list_state_history 能返回 checkpoint 快照列表。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from internal.domain.graph.runtime import GraphRuntime, make_checkpoint_thread_id

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_make_checkpoint_thread_id_adds_tenant_prefix():
    tenant = uuid4()
    key = make_checkpoint_thread_id(tenant, "biz-thread-1")
    assert key == f"{tenant}:biz-thread-1"


def test_runtime_strips_own_tenant_prefix():
    tenant = uuid4()
    runtime = GraphRuntime(
        canvas_json={"nodes": [], "edges": []},
        tenant_id=tenant,
        thread_id=f"{tenant}:biz-thread-1",
        checkpointer=None,
    )
    assert runtime.thread_id == "biz-thread-1"


def test_runtime_rejects_other_tenant_prefix():
    tenant_a = uuid4()
    tenant_b = uuid4()
    with pytest.raises(RuntimeError, match="租户不匹配"):
        GraphRuntime(
            canvas_json={"nodes": [], "edges": []},
            tenant_id=tenant_a,
            thread_id=f"{tenant_b}:biz-thread-1",
            checkpointer=None,
        )


def test_same_biz_thread_id_across_tenants_lands_in_different_checkpoint_keys():
    """两个租户用同一个业务 thread_id，checkpointer 内部存储应是两行不同的 key。"""
    tenant_a = uuid4()
    tenant_b = uuid4()
    shared_biz_thread = "shared-thread"

    saver = InMemorySaver()

    # 用最小可跑的图：start -> end（对齐 fixture 的 coze edge 格式）
    graph = {
        "nodes": [
            {"id": "start_1", "type": "1", "data": {"inputs": {}, "outputs": []}},
            {"id": "end_1", "type": "2", "data": {"inputs": {"content": "ok"}, "outputs": []}},
        ],
        "edges": [
            {"sourceNodeID": "start_1", "targetNodeID": "end_1", "sourcePortID": ""},
        ],
    }

    async def _run(tenant_id):
        rt = GraphRuntime(
            canvas_json=graph,
            tenant_id=tenant_id,
            thread_id=shared_biz_thread,
            checkpointer=saver,
        )
        return await rt.invoke({})

    asyncio.run(_run(tenant_a))
    asyncio.run(_run(tenant_b))

    # 直接看 saver 内部 storage，应包含两条 key（不同 tenant 前缀）
    stored_keys = list(saver.storage.keys())  # type: ignore[attr-defined]
    expected_a = make_checkpoint_thread_id(tenant_a, shared_biz_thread)
    expected_b = make_checkpoint_thread_id(tenant_b, shared_biz_thread)
    assert expected_a in stored_keys
    assert expected_b in stored_keys
    assert expected_a != expected_b


def test_list_state_history_returns_snapshots():
    """跑完一次 invoke 后 list_state_history 应至少返回一条 checkpoint。"""
    tenant = uuid4()
    saver = InMemorySaver()

    graph = {
        "nodes": [
            {"id": "start_1", "type": "1", "data": {"inputs": {}, "outputs": []}},
            {"id": "end_1", "type": "2", "data": {"inputs": {"content": "ok"}, "outputs": []}},
        ],
        "edges": [
            {"sourceNodeID": "start_1", "targetNodeID": "end_1", "sourcePortID": ""},
        ],
    }

    rt = GraphRuntime(
        canvas_json=graph,
        tenant_id=tenant,
        thread_id="hist-thread",
        checkpointer=saver,
    )
    asyncio.run(rt.invoke({}))
    history = asyncio.run(rt.list_state_history(limit=10))
    assert len(history) >= 1
    # 每条快照都应包含 checkpoint_id / next / interrupts / output
    first = history[0]
    assert "checkpoint_id" in first
    assert "next" in first
    assert "interrupts" in first
    assert "output" in first
