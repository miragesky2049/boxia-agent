"""RAG 增强共享函数：Agent 主循环与 Workflow LLMNode 共用。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.retrieval_service import RetrievalService
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork

logger = logging.getLogger(__name__)


async def apply_rag_to_prompt(
    *,
    system_prompt: str,
    retrieval_cfg: dict[str, Any],
    query: str,
    uow: UnitOfWork,
    context: RequestContext,
    history: list[dict[str, Any]] | None = None,
    retrieval_service: RetrievalService | None = None,
) -> str:
    """按 retrieval_cfg 召回相关 chunks，拼到 system_prompt 后面。

    retrieval_cfg 未启用或检索失败时原样返回 system_prompt，不阻断主流程。
    """
    if not retrieval_cfg.get("enabled"):
        return system_prompt

    from internal.infrastructure.config.settings import get_settings

    settings = get_settings()
    document_ids_raw = retrieval_cfg.get("document_ids") or []
    document_ids = [UUID(str(d)) for d in document_ids_raw]
    top_k = int(retrieval_cfg.get("top_k") or settings.rag_top_k)
    threshold = float(
        retrieval_cfg.get("similarity_threshold") or settings.rag_similarity_threshold
    )
    rerank_enabled = bool(
        retrieval_cfg.get("rerank_enabled", settings.rag_rerank_enabled)
    )
    query_rewrite_enabled = bool(
        retrieval_cfg.get("query_rewrite_enabled", settings.rag_query_rewrite_enabled)
    )

    service = retrieval_service or RetrievalService(uow, context)
    try:
        result = await service.search(
            query=query,
            history=history or [],
            document_ids=document_ids,
            top_k=top_k,
            similarity_threshold=threshold,
            enable_query_rewrite=query_rewrite_enabled,
            enable_rerank=rerank_enabled,
            variant_count=settings.rag_query_rewrite_variants,
            recall_multiplier=settings.rag_recall_multiplier,
        )
    except Exception:  # noqa: BLE001 - RAG 失败不阻断主流程
        logger.warning("rag retrieval failed query_len=%d", len(query), exc_info=True)
        return system_prompt

    if not result.context_text:
        return system_prompt

    return (
        f"{system_prompt}\n\n"
        f"以下是从知识库检索到的参考资料，请基于这些内容回答用户问题：\n\n"
        f"{result.context_text}"
    )
