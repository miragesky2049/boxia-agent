"""Prompt 消息判别联合：对齐 OpenAI Chat Completions 的角色与 tool_calls 结构。"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolCallFunction(BaseModel):
    """assistant 消息中请求调用工具的函数签名。"""

    name: str
    arguments: str = ""


class ToolCall(BaseModel):
    """OpenAI tool_calls 数组项。"""

    id: str = Field(default_factory=lambda: f"call_{uuid4().hex[:24]}")
    type: Literal["function"] = "function"
    function: ToolCallFunction


class SystemMessage(BaseModel):
    """系统提示词。"""

    role: Literal["system"] = "system"
    content: str


class UserMessage(BaseModel):
    """用户消息。"""

    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    """助手消息；tool_calls 非空表示本轮请求调用工具。"""

    role: Literal["assistant"] = "assistant"
    content: str = ""
    tool_calls: list[ToolCall] | None = None


class ToolMessage(BaseModel):
    """工具返回结果：tool_call_id 与上一轮 assistant.tool_calls[].id 对应。"""

    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str


ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolMessage,
    Field(discriminator="role"),
]


def system(content: str) -> SystemMessage:
    """构造系统消息。"""
    return SystemMessage(content=content)


def user(content: str) -> UserMessage:
    """构造用户消息。"""
    return UserMessage(content=content)


def assistant(content: str, tool_calls: list[ToolCall] | None = None) -> AssistantMessage:
    """构造助手消息。"""
    return AssistantMessage(content=content, tool_calls=tool_calls)


def tool_result(tool_call_id: str, content: str) -> ToolMessage:
    """构造工具结果消息。"""
    return ToolMessage(tool_call_id=tool_call_id, content=content)
