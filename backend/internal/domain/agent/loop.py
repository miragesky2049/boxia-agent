"""Agent 对话循环：tool-calling 优先，ReAct 兜底。

对齐 coze Agent 运行时核心循环：
1. 拉取会话历史 → 组装 messages
2. 调 LLM（优先 tool-calling 模式）
3. 若返回 tool_calls：逐个执行工具，把结果以 role=tool 追加进 messages，回到步骤 2
4. 若返回纯文本或达到最大轮次：作为最终回复返回

最大轮次保护防止无限循环。
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from internal.domain.agent.model import Message, ToolCall
from internal.domain.agent.repository import ConversationRepository, MessageRepository

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
REACT_ACTION_PATTERN = re.compile(
    r"Thought\s*:\s*(?P<thought>.*?)\s*Action\s*:\s*(?P<action>\w+)\s*"
    r"Action Input\s*:\s*(?P<input>.*?)(?:\s*Observation|$)",
    re.DOTALL,
)


class AgentLoop:
    """Agent 对话循环执行器。

    Args:
        conversation_repo: 会话仓储
        message_repo: 消息仓储
        llm_service: LLM 服务（需实现 async chat(messages, tools=None, **kwargs)）
        tool_registry: 工具注册表 {name: handler}，handler 是 async def(**kwargs) -> str
    """

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
        llm_service: Any,
        tool_registry: dict[str, Any] | None = None,
    ):
        self._conv_repo = conversation_repo
        self._msg_repo = message_repo
        self._llm = llm_service
        self._tools = tool_registry or {}

    async def run(self, conversation_id: UUID, user_input: str) -> str:
        """单轮对话执行：用户输入 → 最终回复文本。"""
        history = await self._msg_repo.list_by_conversation(conversation_id, limit=100)
        messages: list[dict[str, Any]] = [self._to_openai_msg(m) for m in history]
        messages.append({"role": "user", "content": user_input})

        await self._msg_repo.append(Message(
            conversation_id=conversation_id,
            role="user",
            content=user_input,
        ))

        final_text = ""
        for round_idx in range(MAX_TOOL_ROUNDS):
            response = await self._invoke_llm(messages)
            assistant_text = getattr(response, "content", "") or ""
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # 没有工具调用 → 最终回复
                final_text = assistant_text
                await self._msg_repo.append(Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_text,
                ))
                break

            # 先把 assistant 的 tool_calls 追加
            await self._msg_repo.append(Message(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_text,
                tool_calls=[
                    ToolCall(call_id=tc.get("id", ""), name=tc["function"]["name"],
                             arguments=self._parse_args(tc["function"].get("arguments", "{}")))
                    for tc in tool_calls
                ],
            ))
            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": tool_calls,
            })

            # 逐个执行工具
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = self._parse_args(tc["function"].get("arguments", "{}"))
                observation = await self._execute_tool(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": observation,
                })
                await self._msg_repo.append(Message(
                    conversation_id=conversation_id,
                    role="tool",
                    content=observation,
                    tool_call_id=tc.get("id", ""),
                    name=name,
                ))
        else:
            final_text = "（达到最大工具调用轮次，已停止）"

        return final_text

    async def _invoke_llm(self, messages: list[dict[str, Any]]) -> Any:
        """调 LLM：优先传 tools 触发原生 tool-calling。"""
        tools = self._build_tools_schema() if self._tools else None
        return await self._llm.chat(messages=messages, tools=tools)

    def _extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        """从 LLM 响应提取 tool_calls：优先原生字段，否则走 ReAct 解析。"""
        native = getattr(response, "tool_calls", None)
        if native:
            return list(native)

        content = getattr(response, "content", "") or ""
        return self._parse_react_tool_calls(content)

    def _parse_react_tool_calls(self, content: str) -> list[dict[str, Any]]:
        """ReAct 兜底：从文本中解析 Thought/Action/Action Input。"""
        matches = REACT_ACTION_PATTERN.finditer(content)
        calls: list[dict[str, Any]] = []
        for i, m in enumerate(matches):
            calls.append({
                "id": f"react_{i}",
                "type": "function",
                "function": {
                    "name": m.group("action"),
                    "arguments": m.group("input").strip(),
                },
            })
        return calls

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        handler = self._tools.get(name)
        if handler is None:
            return f"[error] 未注册的工具: {name}"
        try:
            result = await handler(**args)
            return str(result)
        except Exception as exc:
            logger.exception("工具执行失败: %s", name)
            return f"[error] {name}: {exc}"

    def _build_tools_schema(self) -> list[dict[str, Any]]:
        """把 tool_registry 转成 OpenAI function calling schema。

        简化：每个工具默认接收任意 JSON 参数（args_schema 在 handler 上可选暴露）。
        """
        schema: list[dict[str, Any]] = []
        for name in self._tools:
            schema.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"tool: {name}",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            })
        return schema

    @staticmethod
    def _to_openai_msg(msg: Message) -> dict[str, Any]:
        out: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            out["tool_call_id"] = msg.tool_call_id
        if msg.name:
            out["name"] = msg.name
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": __import__("json").dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in msg.tool_calls
            ]
        return out

    @staticmethod
    def _parse_args(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        import json
        try:
            return json.loads(str(raw))
        except (json.JSONDecodeError, ValueError):
            # ReAct 文本风格参数不是 JSON，包装为 input 让工具按位置接收
            return {"input": str(raw)}
