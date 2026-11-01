"""Agent 对话循环测试：tool-calling 与 ReAct 兜底。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from internal.domain.agent.loop import AgentLoop
from internal.domain.agent.model import Conversation, Message
from internal.domain.agent.repository import ConversationRepository, MessageRepository


class InMemoryConversationRepo(ConversationRepository):
    def __init__(self) -> None:
        self.store: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.store[conversation.conversation_id] = conversation
        return conversation

    async def get(self, conversation_id: UUID) -> Conversation | None:
        return self.store.get(conversation_id)

    async def list_by_user(self, tenant_id, user_id, app_id=None, limit=20, offset=0):
        return list(self.store.values())

    async def delete(self, conversation_id: UUID) -> None:
        self.store.pop(conversation_id, None)

    async def update_title(self, conversation_id: UUID, title: str) -> None:
        conv = self.store.get(conversation_id)
        if conv:
            self.store[conversation_id] = Conversation(
                conversation_id=conv.conversation_id,
                app_id=conv.app_id,
                tenant_id=conv.tenant_id,
                user_id=conv.user_id,
                title=title,
                created_at=conv.created_at,
                metadata=conv.metadata,
            )


class InMemoryMessageRepo(MessageRepository):
    def __init__(self) -> None:
        self.store: list[Message] = []

    async def append(self, message: Message) -> Message:
        self.store.append(message)
        return message

    async def list_by_conversation(self, conversation_id, limit=100):
        return [m for m in self.store if m.conversation_id == conversation_id][-limit:]

    async def delete(self, message_id: UUID) -> None:
        self.store = [m for m in self.store if m.message_id != message_id]

    async def clear(self, conversation_id: UUID) -> None:
        self.store = [m for m in self.store if m.conversation_id != conversation_id]


class FakeLLM:
    """按脚本返回响应：先 tool_call 一轮，再最终回答。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        resp = self.script[self.calls]
        self.calls += 1
        return resp


class ToolCallResp:
    def __init__(self, content: str, tool_calls: list[dict]):
        self.content = content
        self.tool_calls = tool_calls


class TextResp:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = None


def test_tool_calling_loop_runs_until_final_answer():
    """第一轮 LLM 返回 tool_calls，第二轮返回纯文本，应正确结束。"""
    conv_repo = InMemoryConversationRepo()
    msg_repo = InMemoryMessageRepo()

    weather_result = {"temp": 25}

    async def weather(city: str) -> str:
        return json.dumps({"city": city, **weather_result})

    llm = FakeLLM([
        ToolCallResp(
            content="",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "weather",
                    "arguments": json.dumps({"city": "北京"}),
                },
            }],
        ),
        TextResp(content="北京今天 25 度。"),
    ])

    loop = AgentLoop(conv_repo, msg_repo, llm, tool_registry={"weather": weather})

    conv = Conversation()
    import asyncio
    asyncio.run(conv_repo.create(conv))

    final = asyncio.run(loop.run(conv.conversation_id, "北京天气怎么样"))
    assert "25" in final

    # 应该有 user / assistant(tool_calls) / tool / assistant 共 4 条消息
    roles = [m.role for m in msg_repo.store]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_react_fallback_when_no_native_tool_calls():
    """LLM 不支持原生 tool_calls 时，从文本解析 ReAct Action。"""
    conv_repo = InMemoryConversationRepo()
    msg_repo = InMemoryMessageRepo()

    captured: dict[str, str] = {}

    async def calculator(input: str = "", expr: str = "") -> str:
        arg = expr or input
        captured["expr"] = arg
        # 测试桩：仅支持 "1+2" 形式，不引入 eval 安全风险
        left, right = arg.split("+")
        return str(int(left.strip()) + int(right.strip()))

    llm = FakeLLM([
        TextResp(content="Thought: 需要计算\nAction: calculator\nAction Input: 1+2\nObservation: 3\nThought: 知道了"),
        TextResp(content="1+2=3"),
    ])

    loop = AgentLoop(conv_repo, msg_repo, llm, tool_registry={"calculator": calculator})
    import asyncio
    conv = asyncio.run(conv_repo.create(Conversation()))

    final = asyncio.run(loop.run(conv.conversation_id, "算一下 1+2"))
    assert "3" in final
    assert captured["expr"] == "1+2"
