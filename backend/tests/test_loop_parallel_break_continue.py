"""T11：并发 Loop 的 break/continue 语义单测。

并发模式下：
- break：任一迭代产出 __break__ 后，取消其余 pending 任务，触发 break 的迭代本身不入结果。
- continue：产出 __continue__ 的迭代跳过输出，其余迭代照常完成。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.loop import LoopNodeHandler


def _make_ctx() -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="t",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="loop_1",
        node_type="21",
        inputs={},
        config={},
        env=env,
        services=ServiceRegistry(),
    )


def test_parallel_break_cancels_remaining_iterations() -> None:
    handler = LoopNodeHandler()
    ctx = _make_ctx()

    started: list[int] = []
    cancelled: list[int] = []

    async def fake_invoke(_ctx, _compiled, item: Any, index: int, total: int) -> dict[str, Any]:
        started.append(index)
        try:
            # 越靠后的索引耗时越长，确保 break 触发时 2/3/4 仍在跑
            await asyncio.sleep(0.02 * (index + 1))
        except asyncio.CancelledError:
            cancelled.append(index)
            raise
        if index == 1:
            return {
                "node_outputs": {"break_node": {"__break__": True}},
                "output": {"v": item},
            }
        return {"node_outputs": {}, "output": {"v": item}}

    handler._invoke_once = fake_invoke  # type: ignore[assignment]

    items = [10, 20, 30, 40, 50]
    results = asyncio.run(handler._run_parallel(ctx, compiled=None, items=items, total=len(items)))

    # index 0 在 break 前已完成，应保留；index 1 是 break 触发者，不写入
    assert results == [{"v": 10}]
    # 2/3/4 应被取消
    assert 2 in cancelled
    assert 3 in cancelled
    assert 4 in cancelled


def test_parallel_continue_skips_only_that_iteration() -> None:
    handler = LoopNodeHandler()
    ctx = _make_ctx()

    async def fake_invoke(_ctx, _compiled, item: Any, index: int, total: int) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        if index == 2:
            return {
                "node_outputs": {"continue_node": {"__continue__": True}},
                "output": {"v": item},
            }
        return {"node_outputs": {}, "output": {"v": item}}

    handler._invoke_once = fake_invoke  # type: ignore[assignment]

    items = [10, 20, 30, 40]
    results = asyncio.run(handler._run_parallel(ctx, compiled=None, items=items, total=len(items)))

    # index 2 被跳过，其余按原顺序保留
    assert results == [{"v": 10}, {"v": 20}, {"v": 40}]
