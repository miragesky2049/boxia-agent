"""Embedding 客户端：OpenAI 兼容 /v1/embeddings 协议。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient(ABC):
    """Embedding 客户端抽象：业务代码只依赖该接口，便于替换厂商或本地模型。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化；返回与输入等长的向量列表。"""


class OpenAICompatEmbeddingClient(EmbeddingClient):
    """OpenAI Embeddings 兼容客户端（SiliconFlow / DashScope / 智谱 / vLLM 通用）。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("EMBEDDING_API_KEY 未配置，无法初始化 Embedding 客户端")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量调用 /embeddings；空列表直接返回空，避免无意义请求。"""
        if not texts:
            return []

        payload = {"model": self._model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/embeddings"
        logger.info(
            "embedding request model=%s batch=%d",
            self._model,
            len(texts),
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        items = data.get("data") or []
        # 按 index 字段排序，防止网关返回顺序与输入不一致
        items.sort(key=lambda item: int(item.get("index") or 0))
        return [[float(x) for x in (item.get("embedding") or [])] for item in items]
