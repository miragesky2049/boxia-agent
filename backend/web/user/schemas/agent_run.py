"""用户端 agent 运行请求/响应模型。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """历史消息项。"""

    role: str = Field(pattern="^(user|assistant)$")
    content: str


class AgentRunRequest(BaseModel):
    """运行一次 agent 的请求体。"""

    query: str = Field(min_length=1, max_length=8000)
    # 会话 ID：调用方保持同一对话不变，便于后续扩展长期记忆
    conversation_id: str = Field(default="", max_length=128)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=40)


class ToolCallTraceOut(BaseModel):
    """单次工具调用轨迹。"""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    observation: str
    is_error: bool


class AgentRunResponse(BaseModel):
    """运行结果。"""

    agent_id: UUID
    run_id: str
    conversation_id: str
    content: str
    tool_traces: list[ToolCallTraceOut]
    iterations: int
    usage: dict[str, int]
    finish_reason: str
