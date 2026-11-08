"""Agent 领域模型：Conversation / Message / ToolCall。

对齐 coze 的 conversation 与 message 数据结构，作为 Agent 对话循环与节点操作的统一抽象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ToolCall:
    """LLM 发起的工具调用请求。"""

    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Message:
    """一条对话消息。

    role: "system" / "user" / "assistant" / "tool"
    """

    conversation_id: UUID
    role: str
    content: str = ""
    message_id: UUID = field(default_factory=uuid4)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    created_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Conversation:
    """一次会话：属于某个应用 + 某个用户 + 某个租户。"""

    conversation_id: UUID = field(default_factory=uuid4)
    app_id: UUID | None = None
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    title: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)
