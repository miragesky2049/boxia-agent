"""Rerank 客户端：Cross-Encoder 精排，对向量召回的候选 chunk 做相关性打分。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankResult:
    """单条文档的 rerank 打分结果。"""

    index: int
    score: float


class RerankClient(ABC):
    """Rerank 客户端抽象：业务代码只依赖该接口，便于替换厂商。"""

    @abstractmethod
    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[RerankResult]:
        """对 query-documents 对做相关性打分，返回 top_n 条（已按 score 降序）。"""


class SiliconFlowRerankClient(RerankClient):
    """SiliconFlow /v1/rerank 兼容客户端（Jina/Cohere 风格协议）。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Rerank API Key 未配置，无法初始化 Rerank 客户端")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[RerankResult]:
        """调用 /rerank；documents 为空时直接返回空列表。"""
        if not query.strip() or not documents:
            return []

        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/rerank"
        logger.info(
            "rerank request model=%s candidates=%d top_n=%d",
            self._model,
            len(documents),
            top_n,
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("results") or []
        parsed: list[RerankResult] = []
        for item in results:
            idx = int(item.get("index") or 0)
            score = float(item.get("relevance_score") or item.get("score") or 0.0)
            parsed.append(RerankResult(index=idx, score=score))
        # 兜底按 score 降序
        parsed.sort(key=lambda r: r.score, reverse=True)
        return parsed
