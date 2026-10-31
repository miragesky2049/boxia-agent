"""LLM 服务适配器：把 ModelService 返回的 LLMClient 适配成节点期望的接口。

domain/graph/nodes/llm.py 期望：
    await llm_service.chat(messages, model, temperature, max_tokens, response_format, tools)
    -> LLMResponse(content, tool_calls, usage)

老 LLMClient 是按 model 构造的（model 已 bake 进 client），且签名带 tools/response_format 等。
本适配器接收一个 model_resolver 函数，在调用时按 model 取对应 client，再透传采样参数。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable
from uuid import UUID

from internal.domain.llm.client import LLMClient, LLMResponse, LLMToolSpec


class LLMServiceAdapter:
    """节点侧 llm 服务：按 model_id 动态取 LLMClient。"""

    def __init__(self, model_resolver: Callable[[str], LLMClient]):
        self._resolver = model_resolver

    async def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[LLMToolSpec] | None = None,
    ) -> Any:
        """返回 LLMResponse（domain llm 节点已按 .content / .usage / .tool_calls 解构）。"""
        client = self._resolver(model)
        return await client.chat(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    async def chat_stream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """流式 chat：逐 chunk yield LLMResponse（content 为增量 delta）。

        流式路径不支持 tools（tool_calls 由非流式 chat 路径处理）。
        """
        client = self._resolver(model)
        async for chunk in client.chat_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ):
            yield chunk


def build_model_resolver(
    model_service: Any,
    tenant_id: UUID,
) -> Callable[[str], LLMClient]:
    """包一个 model_id -> LLMClient 的闭包，绑定当前租户。"""

    def _resolve(model_id: str) -> LLMClient:
        return model_service.get_client_for_tenant(model_id, tenant_id)

    return _resolve
