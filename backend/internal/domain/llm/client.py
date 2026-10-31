"""LLM 客户端抽象与 OpenAI 兼容实现（DeepSeek / Qwen / 私有网关通用）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel, Field

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.llm.messages import AssistantMessage, ToolCall, ToolCallFunction
from internal.infrastructure.observability.metrics import LLM_DURATION, LLM_TOKENS

logger = logging.getLogger(__name__)


def _tenant_label(context: AgentRunContext | None) -> str:
    """tenant 短码：平台资源用 platform，其他用 UUID 前 8 位避免高基数。"""
    if context is None:
        return "anonymous"
    if context.tenant_id == PLATFORM_TENANT_ID:
        return "platform"
    return context.tenant_id.hex[:8]

# 共享 httpx.AsyncClient 池：按 base_url 缓存，避免每次调用新建连接。
# 进程关闭时由 lifespan 统一关闭。
_client_pool: dict[str, httpx.AsyncClient] = {}

# 可重试的 HTTP 状态码：429（限流）+ 5xx（网关/上游错误）
_RETRYABLE_STATUSES = {429, 502, 503, 504}
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = (0.5, 1.0)


async def shutdown_llm_clients() -> None:
    """关闭所有共享 httpx client，应在应用 shutdown 钩子中调用。"""
    global _client_pool
    for client in _client_pool.values():
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            logger.warning("failed to close shared httpx client", exc_info=True)
    _client_pool.clear()


def _get_shared_client(base_url: str, timeout: httpx.Timeout) -> httpx.AsyncClient:
    """按 base_url 取共享 client；不存在则创建。

    不同 timeout 视为同一 client（timeout 在每次请求时可覆盖）。
    http2 依赖 h2 包，未安装时自动降级为 http/1.1。
    """
    key = base_url
    client = _client_pool.get(key)
    if client is None or client.is_closed:
        try:
            client = httpx.AsyncClient(
                timeout=timeout,
                http2=True,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
        except ImportError:
            client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
        _client_pool[key] = client
    return client


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
        response_format: dict[str, Any] | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
    ) -> LLMResponse:
        """调用 /chat/completions 并返回聚合结果。

        response_format: 可选，OpenAI response_format 字典（如 {"type": "json_object"}），
                        模型不支持时由网关返回 4xx，调用方自行处理。
        top_p / presence_penalty / frequency_penalty: OpenAI Chat Completions 标准采样参数，
                        None 时不传，由网关默认值决定。
        """

    async def chat_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: AgentRunContext | None = None,
        response_format: dict[str, Any] | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """流式 chat：逐 chunk yield LLMResponse（content 为当次增量）。

        默认实现退化为一次性 chat：调用方可以基于 chat 实现兼容旧客户端。
        最后一个 chunk 的 content 为完整聚合文本；其他 chunk 为增量 delta。
        约定：
          - 每个 yield 的 content 是当次增量（非累积）；
          - 结束时再 yield 一个 content="" 且 usage 填好的收尾 chunk（可选）。
        """
        resp = await self.chat(
            messages=messages,
            tools=None,
            temperature=temperature,
            max_tokens=max_tokens,
            context=context,
            response_format=response_format,
            top_p=top_p,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
        )
        yield resp


class OpenAICompatLLMClient(LLMClient):
    """OpenAI Chat Completions 兼容客户端（DeepSeek 默认即兼容该协议）。

    生产级特性：
      - 共享 httpx.AsyncClient（HTTP/2 + 连接池 + keep-alive）
      - 对 429/5xx/超时自动重试（最多 2 次，指数退避）
    """

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
        response_format: dict[str, Any] | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
    ) -> LLMResponse:
        """发起一次非流式 chat completions 调用，带自动重试。"""
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
        if response_format is not None:
            payload["response_format"] = response_format
        # OpenAI 标准采样参数：None 时不传，避免覆盖网关默认值
        if top_p is not None:
            payload["top_p"] = top_p
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty

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

        client = _get_shared_client(self._base_url, self._timeout)

        started = time.perf_counter()
        tenant = _tenant_label(context)
        status = "success"
        result: LLMResponse | None = None
        try:
            last_exc: Exception | None = None
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    status = "success"
                    if response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                        retry_after = response.headers.get("Retry-After")
                        backoff = _RETRY_BACKOFF_SECONDS[attempt] if attempt < len(_RETRY_BACKOFF_SECONDS) else 1.0
                        if retry_after:
                            try:
                                backoff = max(backoff, float(retry_after))
                            except ValueError:
                                pass
                        logger.warning(
                            "llm retry attempt=%d status=%d backoff=%.1fs",
                            attempt + 1,
                            response.status_code,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    result = self._parse_response(data)
                    return result
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_exc = exc
                    status = "network_error"
                    if attempt < _MAX_RETRIES:
                        backoff = _RETRY_BACKOFF_SECONDS[attempt]
                        logger.warning(
                            "llm network retry attempt=%d err=%s backoff=%.1fs",
                            attempt + 1,
                            type(exc).__name__,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise
                except httpx.HTTPStatusError as exc:
                    # 非可重试状态码直接抛
                    status = f"http_{exc.response.status_code}"
                    raise
        finally:
            duration = time.perf_counter() - started
            LLM_DURATION.labels(tenant=tenant, model=self._model, status=status).observe(duration)
            if result is not None:
                LLM_TOKENS.labels(tenant=tenant, model=self._model, type="prompt").inc(
                    result.usage.prompt_tokens
                )
                LLM_TOKENS.labels(tenant=tenant, model=self._model, type="completion").inc(
                    result.usage.completion_tokens
                )

        # 理论上不会走到这里（要么 return 要么 raise）
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM request failed for unknown reason")

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

    async def chat_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: AgentRunContext | None = None,
        response_format: dict[str, Any] | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """OpenAI 兼容 SSE 流式调用：逐 chunk yield LLMResponse（content 为增量）。

        约定：
          - 每个 yield 的 content 是当次增量 delta；
          - 不支持 tools（流式 + tool_calls 在 SSE 中需要聚合 partial tool_calls，
            由非流式 chat 路径处理）；
          - 流结束时 yield 一个 finish_reason="stop" 的收尾 chunk（content 可能为空）。
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._default_temperature if temperature is None else temperature,
            "max_tokens": self._default_max_tokens if max_tokens is None else max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if top_p is not None:
            payload["top_p"] = top_p
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if context is not None:
            headers.update(context.llm_headers())

        url = f"{self._base_url}/chat/completions"
        client = _get_shared_client(self._base_url, self._timeout)

        started = time.perf_counter()
        tenant = _tenant_label(context)
        status = "success"
        finish_reason = "stop"
        usage = LLMUsage()
        model = self._model
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code in _RETRYABLE_STATUSES:
                    # 流开启后再收到可重试状态码，直接抛；调用方决定要不要退化为 chat。
                    status = f"http_{response.status_code}"
                    await response.aread()
                    raise httpx.HTTPStatusError(
                        f"llm stream status={response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.strip():
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if "model" in data:
                        model = data["model"] or model
                    usage_raw = data.get("usage")
                    if isinstance(usage_raw, dict) and usage_raw:
                        usage = LLMUsage(
                            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                            total_tokens=int(usage_raw.get("total_tokens") or 0),
                        )

                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                    reason = choice.get("finish_reason")
                    if reason:
                        finish_reason = reason
                    if delta:
                        yield LLMResponse(
                            content=delta,
                            finish_reason=finish_reason,
                            model=model,
                        )

            yield LLMResponse(content="", finish_reason=finish_reason, usage=usage, model=model)
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.perf_counter() - started
            LLM_DURATION.labels(tenant=tenant, model=self._model, status=status).observe(duration)
            if usage.prompt_tokens:
                LLM_TOKENS.labels(tenant=tenant, model=self._model, type="prompt").inc(
                    usage.prompt_tokens
                )
            if usage.completion_tokens:
                LLM_TOKENS.labels(tenant=tenant, model=self._model, type="completion").inc(
                    usage.completion_tokens
                )


def assistant_message_from_response(response: LLMResponse) -> AssistantMessage:
    """把 LLMResponse 转换为下一轮要回写的 assistant 消息。"""
    return AssistantMessage(
        content=response.content,
        tool_calls=response.tool_calls or None,
    )
