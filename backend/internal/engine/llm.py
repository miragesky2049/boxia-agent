"""LLM 客户端抽象与 OpenAI 兼容实现（DeepSeek / Qwen / 私有网关通用）。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field

from internal.engine.context import AgentRunContext
from internal.engine.messages import AssistantMessage, ToolCall, ToolCallFunction

logger = logging.getLogger(__name__)


class LLMToolSpec(BaseModel):
    """向模型暴露的工具描述（OpenAI tools 数组格式）。"""

    name: str
    description: str = ""
    # JSON Schema，描述工具入参
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_openai(self) -> dict[str, Any]:
        """序列化为 OpenAI /chat/completions tools 数组项。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class LLMUsage(BaseModel):
    """token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """LLM 单轮响应。"""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model: str = ""

    @property
    def wants_tool_call(self) -> bool:
        """本轮是否请求调用工具。"""
        return bool(self.tool_calls)


class LLMClient(ABC):
    """LLM 客户端抽象：业务代码只依赖该接口，便于后续替换厂商。"""

    @abstractmethod
    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[LLMToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: AgentRunContext | None = None,
    ) -> LLMResponse:
        """调用 /chat/completions 并返回聚合结果。"""


class OpenAICompatLLMClient(LLMClient):
    """OpenAI Chat Completions 兼容客户端（DeepSeek 默认即兼容该协议）。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 60.0,
        default_temperature: float = 0.7,
        default_max_tokens: int = 1024,
    ) -> None:
        if not api_key:
            raise ValueError("LLM_API_KEY 未配置，无法初始化 LLM 客户端")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[LLMToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: AgentRunContext | None = None,
    ) -> LLMResponse:
        """发起一次非流式 chat completions 调用。"""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._default_temperature if temperature is None else temperature,
            "max_tokens": self._default_max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = [tool.to_openai() for tool in tools]
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if context is not None:
            headers.update(context.llm_headers())

        url = f"{self._base_url}/chat/completions"
        logger.info(
            "llm request model=%s messages=%d tools=%d run_id=%s",
            self._model,
            len(messages),
            len(tools) if tools else 0,
            context.run_id if context else "-",
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data)

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMResponse:
        """把 OpenAI 兼容响应归一化为 LLMResponse。"""
        choices = data.get("choices") or []
        if not choices:
            return LLMResponse(model=data.get("model", ""))
        choice = choices[0]
        message = choice.get("message") or {}
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = [
            ToolCall(
                id=item.get("id") or f"call_{idx:04d}",
                function=ToolCallFunction(
                    name=(item.get("function") or {}).get("name", ""),
                    arguments=(item.get("function") or {}).get("arguments", "") or "",
                ),
            )
            for idx, item in enumerate(raw_tool_calls)
        ]
        usage_raw = data.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
        )
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason") or "stop",
            usage=usage,
            model=data.get("model", ""),
        )


def assistant_message_from_response(response: LLMResponse) -> AssistantMessage:
    """把 LLMResponse 转换为下一轮要回写的 assistant 消息。"""
    return AssistantMessage(
        content=response.content,
        tool_calls=response.tool_calls or None,
    )
