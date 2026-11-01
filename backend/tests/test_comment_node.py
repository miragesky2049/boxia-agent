"""T10: Comment 便签节点（type=31）单测。

便签节点无执行语义，handler 直接返回空 outputs；不依赖任何 service。
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.comment import CommentNodeHandler
from internal.domain.graph.nodes import get_node_handler, list_registered_types


def test_comment_handler_registered() -> None:
    assert NodeType.COMMENT.value in list_registered_types()
    handler = get_node_handler(NodeType.COMMENT.value)
    assert isinstance(handler, CommentNodeHandler)


def test_comment_run_returns_empty_outputs() -> None:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="t",
        application_id=uuid4(),
    )
    ctx = NodeContext(
        node_id="comment_1",
        node_type=NodeType.COMMENT.value,
        inputs={},
        config={"content": "这是一段说明"},
        env=env,
        services=ServiceRegistry(),
    )
    result = asyncio.run(CommentNodeHandler().run(ctx))
    assert result.outputs == {}
    assert result.route is None
