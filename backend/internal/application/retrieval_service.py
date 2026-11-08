"""RAG 检索用例：query 改写 → 多 query 并行召回 → 去重 → rerank 精排 → 注入 prompt。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from uuid import UUID

from internal.domain.entity.document import DocumentChunk
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.domain.retrieval.embedding import EmbeddingClient
from internal.domain.retrieval.query_rewrite import QueryRewriter, QueryRewriteResult
from internal.domain.retrieval.rerank import RerankClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    """单次检索结果：拼到 system_prompt 后面的文本 + 命中的 chunk 列表。"""

    chunks: list[DocumentChunk]
    # 拼装后的上下文文本：直接可注入 prompt
    context_text: str
    # 改写后的实际 query（用于审计/调试）
    standalone_query: str = ""
    # 实际用于召回的 query 列表
    recalled_queries: list[str] = field(default_factory=list)


class RetrievalService:
    """检索用例：query_rewrite → multi-query recall → rerank → filter。"""

    def __init__(
        self,
        uow: UnitOfWork,
        context: RequestContext,
        embedding_client: EmbeddingClient | None = None,
        rerank_client: RerankClient | None = None,
        query_rewriter: QueryRewriter | None = None,
    ) -> None:
        self._uow = uow
        self._context = context
        self._embedding_client = embedding_client
        self._rerank_client = rerank_client
        self._query_rewriter = query_rewriter

    async def search(
        self,
        *,
        query: str,
        history: list[dict] | None = None,
        document_ids: list[UUID] | None = None,
        top_k: int = 5,
        similarity_threshold: float = 0.55,
        rerank_threshold: float = 0.1,
        enable_query_rewrite: bool = True,
        enable_rerank: bool = True,
        variant_count: int = 3,
        recall_multiplier: int = 10,
    ) -> RetrievalResult:
        """执行检索全流程。

        Args:
            query: 用户原始问题
            history: 最近对话历史（用于消解指代）
            document_ids: 限定只检索这些文档（agent 绑定知识库）
            top_k: 最终返回 chunk 数
            similarity_threshold: 向量余弦阈值（rerank 关闭时使用）
            rerank_threshold: rerank 分数阈值（rerank 开启时使用，bge-reranker 分数分布 0~1，
                              相关文档通常 >0.5，不相关 <0.05；默认 0.1 过滤弱相关噪声）
            enable_query_rewrite: 是否启用 LLM query 改写
            enable_rerank: 是否启用 cross-encoder 精排
            variant_count: 多 query 变体数
            recall_multiplier: 向量召回倍数（粗排候选 = top_k * multiplier）
        """
        if not query.strip():
            return RetrievalResult(chunks=[], context_text="")

        # 1. Query 改写
        rewrite = await self._rewrite_query(
            query=query,
            history=history or [],
            enable=enable_query_rewrite,
            variant_count=variant_count,
        )
        embed_queries = rewrite.all_queries

        # 2. 并行 embedding + 向量召回
        recall_limit = top_k * recall_multiplier
        candidates = await self._recall_multi_query(
            queries=embed_queries,
            document_ids=document_ids,
            recall_limit=recall_limit,
        )
        if not candidates:
            return RetrievalResult(
                chunks=[],
                context_text="",
                standalone_query=rewrite.standalone,
                recalled_queries=embed_queries,
            )

        # 3. Rerank 精排
        final_chunks = await self._maybe_rerank(
            standalone=rewrite.standalone,
            candidates=candidates,
            top_k=top_k,
            enable=enable_rerank and self._rerank_client is not None,
            rerank_threshold=rerank_threshold,
            vector_threshold=similarity_threshold,
        )

        context_text = self._build_context(final_chunks)
        logger.info(
            "retrieval query_len=%d queries=%d candidates=%d final=%d rerank=%s",
            len(query),
            len(embed_queries),
            len(candidates),
            len(final_chunks),
            enable_rerank and self._rerank_client is not None,
        )
        return RetrievalResult(
            chunks=final_chunks,
            context_text=context_text,
            standalone_query=rewrite.standalone,
            recalled_queries=embed_queries,
        )

    async def _rewrite_query(
        self,
        *,
        query: str,
        history: list[dict],
        enable: bool,
        variant_count: int,
    ) -> QueryRewriteResult:
        """调用 LLM 改写；未启用或 rewriter 为空时直接返回原 query。"""
        if not enable or self._query_rewriter is None:
            return QueryRewriteResult(standalone=query, variants=[])
        try:
            return await self._query_rewriter.rewrite(
                query=query,
                history=history,
                variant_count=variant_count,
            )
        except Exception:  # noqa: BLE001 - 改写失败不阻断召回
            logger.warning("query rewrite failed, fallback to raw query", exc_info=True)
            return QueryRewriteResult(standalone=query, variants=[])

    async def _recall_multi_query(
        self,
        *,
        queries: list[str],
        document_ids: list[UUID] | None,
        recall_limit: int,
    ) -> list[DocumentChunk]:
        """对多个 query 并行 embedding + 向量召回，按 (document_id, chunk_index) 去重合并。"""
        client = self._resolve_embedding_client()
        embeddings = await client.embed(queries)

        async def _one(vec: list[float]) -> list[DocumentChunk]:
            return self._uow.document_chunks.search_similar(
                vec,
                top_k=recall_limit,
                document_ids=document_ids,
            )

        results = await asyncio.gather(*[_one(vec) for vec in embeddings], return_exceptions=True)

        # 按 (document_id, chunk_index) 去重，保留最高分
        merged: dict[tuple[UUID, int], DocumentChunk] = {}
        for item in results:
            if isinstance(item, BaseException):
                logger.warning("recall for one query failed: %s", item)
                continue
            for chunk in item:
                key = (chunk.document_id, chunk.chunk_index)
                existing = merged.get(key)
                if existing is None or chunk.score > existing.score:
                    merged[key] = chunk

        # 按向量 score 降序
        return sorted(merged.values(), key=lambda c: c.score, reverse=True)

    async def _maybe_rerank(
        self,
        *,
        standalone: str,
        candidates: list[DocumentChunk],
        top_k: int,
        enable: bool,
        rerank_threshold: float,
        vector_threshold: float,
    ) -> list[DocumentChunk]:
        """根据开关决定走 rerank 精排还是直接按向量 score 过滤。"""
        if not enable:
            return [c for c in candidates if c.score >= vector_threshold][:top_k]

        docs = [c.content for c in candidates]
        try:
            reranked = await self._rerank_client.rerank(  # type: ignore[union-attr]
                query=standalone,
                documents=docs,
                top_n=min(top_k * 2, len(docs)),
            )
        except Exception:  # noqa: BLE001 - rerank 失败降级为向量分数过滤
            logger.warning("rerank failed, fallback to vector score", exc_info=True)
            return [c for c in candidates if c.score >= vector_threshold][:top_k]

        # 把 rerank 分数回填到 chunk；用 dataclass.replace 注入 rerank_score
        reranked_chunks: list[DocumentChunk] = []
        for result in reranked:
            if result.index >= len(candidates):
                continue
            chunk = candidates[result.index]
            if result.score < rerank_threshold:
                continue
            reranked_chunks.append(dc_replace(chunk, rerank_score=result.score, score=result.score))
        return reranked_chunks[:top_k]

    @staticmethod
    def _build_context(chunks: list[DocumentChunk]) -> str:
        """把命中的 chunk 拼成可注入 prompt 的上下文段落，带标题路径。"""
        if not chunks:
            return ""
        blocks: list[str] = []
        for idx, chunk in enumerate(chunks):
            heading_path = chunk.metadata.get("heading_path") or []
            heading_label = " > ".join(heading_path) if heading_path else ""
            header = f"[资料 {idx + 1} | {heading_label}]" if heading_label else f"[资料 {idx + 1}]"
            blocks.append(f"{header}\n{chunk.content}")
        return "\n\n".join(blocks)

    def _resolve_embedding_client(self) -> EmbeddingClient:
        """构造 embedding 客户端；测试可注入，生产从 settings 读取。"""
        if self._embedding_client is not None:
            return self._embedding_client
        from internal.domain.retrieval.embedding import OpenAICompatEmbeddingClient
        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        return OpenAICompatEmbeddingClient(
            api_key=settings.embedding_api_key.get_secret_value(),
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
