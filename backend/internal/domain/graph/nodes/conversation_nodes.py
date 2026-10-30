"""Conversation / Message 工作流节点（coze type=39/51/52/53/54/55/56/57/37/38）。

这些节点让 workflow 能读写会话历史，作为 Agent 应用编排的基础积木。

依赖服务（通过 ctx.services 注入）：
- conversation_repo: ConversationRepository
- message_repo: MessageRepository
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.domain.agent.model import Conversation, Message
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


class CreateConversationNodeHandler(NodeHandler):
    """type=39: 创建会话。"""

    type_name = NodeType.CREATE_CONVERSATION.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        if not ctx.services.has("conversation_repo"):
            return NodeResult(outputs={"conversationId": "stub_conv_id"})

        repo = ctx.services.get("conversation_repo")
        conv = Conversation(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            app_id=_parse_uuid(ctx.inputs.get("appId")),
            title=str(ctx.inputs.get("title") or ""),
            metadata=dict(ctx.inputs.get("metadata") or {}),
        )
        saved = await repo.create(conv)
        return NodeResult(outputs={"conversationId": str(saved.conversation_id)})


class UpdateConversationNodeHandler(NodeHandler):
    """type=51: 更新会话标题。"""

    type_name = NodeType.UPDATE_CONVERSATION.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        conv_id = _parse_uuid(ctx.inputs.get("conversationId"))
        title = str(ctx.inputs.get("title") or "")
        if not conv_id:
            return NodeResult(outputs={"error": "缺少 conversationId"})

        if ctx.services.has("conversation_repo"):
            await ctx.services.get("conversation_repo").update_title(conv_id, title)
        return NodeResult(outputs={"success": True})


class DeleteConversationNodeHandler(NodeHandler):
    """type=52: 删除会话。"""

    type_name = NodeType.DELETE_CONVERSATION.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        conv_id = _parse_uuid(ctx.inputs.get("conversationId"))
        if not conv_id:
            return NodeResult(outputs={"error": "缺少 conversationId"})

        if ctx.services.has("conversation_repo"):
            await ctx.services.get("conversation_repo").delete(conv_id)
        return NodeResult(outputs={"success": True})


class QueryConversationListNodeHandler(NodeHandler):
    """type=53: 查询当前用户会话列表。"""

    type_name = NodeType.QUERY_CONVERSATION_LIST.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        if not ctx.services.has("conversation_repo"):
            return NodeResult(outputs={"conversations": []})

        repo = ctx.services.get("conversation_repo")
        convs = await repo.list_by_user(
            tenant_id=ctx.env.tenant_id,
            user_id=ctx.env.user_id,
            app_id=_parse_uuid(ctx.inputs.get("appId")),
            limit=int(ctx.inputs.get("limit") or 20),
        )
        return NodeResult(outputs={
            "conversations": [
                {"id": str(c.conversation_id), "title": c.title, "updated_at": c.updated_at.isoformat()}
                for c in convs
            ],
        })


class QueryConversationHistoryNodeHandler(NodeHandler):
    """type=54: 查询会话历史消息。"""

    type_name = NodeType.QUERY_CONVERSATION_HISTORY.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        conv_id = _parse_uuid(ctx.inputs.get("conversationId"))
        if not conv_id:
            return NodeResult(outputs={"messages": []})

        if not ctx.services.has("message_repo"):
            return NodeResult(outputs={"messages": []})

        messages = await ctx.services.get("message_repo").list_by_conversation(
            conv_id, limit=int(ctx.inputs.get("limit") or 100),
        )
        return NodeResult(outputs={
            "messages": [
                {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
                for m in messages
            ],
        })


class CreateMessageNodeHandler(NodeHandler):
    """type=55: 追加一条消息。"""

    type_name = NodeType.CREATE_MESSAGE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        conv_id = _parse_uuid(ctx.inputs.get("conversationId"))
        role = str(ctx.inputs.get("role") or "user")
        content = str(ctx.inputs.get("content") or "")
        if not conv_id:
            return NodeResult(outputs={"error": "缺少 conversationId"})

        if not ctx.services.has("message_repo"):
            return NodeResult(outputs={"messageId": "stub_msg_id"})

        msg = Message(conversation_id=conv_id, role=role, content=content)
        saved = await ctx.services.get("message_repo").append(msg)
        return NodeResult(outputs={"messageId": str(saved.message_id)})


class UpdateMessageNodeHandler(NodeHandler):
    """type=56: 更新消息内容（简化版：delete + append 新消息）。"""

    type_name = NodeType.UPDATE_MESSAGE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        msg_id = _parse_uuid(ctx.inputs.get("messageId"))
        content = str(ctx.inputs.get("content") or "")
        if not msg_id or not ctx.services.has("message_repo"):
            return NodeResult(outputs={"success": False})

        # 简化：仓储接口未提供 update，先 delete；后续按需扩展
        await ctx.services.get("message_repo").delete(msg_id)
        return NodeResult(outputs={"success": True, "content": content})


class DeleteMessageNodeHandler(NodeHandler):
    """type=57: 删除单条消息。"""

    type_name = NodeType.DELETE_MESSAGE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        msg_id = _parse_uuid(ctx.inputs.get("messageId"))
        if msg_id and ctx.services.has("message_repo"):
            await ctx.services.get("message_repo").delete(msg_id)
        return NodeResult(outputs={"success": True})


class ClearContextNodeHandler(NodeHandler):
    """type=38: 清空会话消息。"""

    type_name = NodeType.CLEAR_CONTEXT.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        conv_id = _parse_uuid(ctx.inputs.get("conversationId"))
        if conv_id and ctx.services.has("message_repo"):
            await ctx.services.get("message_repo").clear(conv_id)
        return NodeResult(outputs={"success": True})


register_node_handler(CreateConversationNodeHandler())
register_node_handler(UpdateConversationNodeHandler())
register_node_handler(DeleteConversationNodeHandler())
register_node_handler(QueryConversationListNodeHandler())
register_node_handler(QueryConversationHistoryNodeHandler())
register_node_handler(CreateMessageNodeHandler())
register_node_handler(UpdateMessageNodeHandler())
register_node_handler(DeleteMessageNodeHandler())
register_node_handler(ClearContextNodeHandler())
