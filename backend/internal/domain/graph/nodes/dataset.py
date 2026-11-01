"""Dataset 检索节点（coze type=6）：向量近邻检索知识库。

config 约定：
- datasetId: 目标知识库
- topK: 返回条数（默认 5）
- retrievalMode: 检索模式（vector / text / mix，阶段先支持 vector）

inputs:
- query: 待检索文本（由 compiler 求值）

依赖服务（通过 ctx.services 注入）：
- embedding: 文本 → 向量（需实现 async embed(texts: list[str]) -> list[list[float]]）
- vector_store: VectorStore 实例
"""

from __future__ import annotations

import logging
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class DatasetNodeHandler(NodeHandler):
    type_name = NodeType.DATASET.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        dataset_id = str(config.get("datasetId") or "")
        top_k = int(config.get("topK") or 5)
        query = ctx.inputs.get("query")

        if not dataset_id:
            return NodeResult(outputs={"error": "dataset 节点缺少 datasetId"})
        if query is None:
            return NodeResult(outputs={"chunks": [], "error": "dataset 节点缺少 query"})

        if not ctx.services.has("vector_store") or not ctx.services.has("embedding"):
            # 开发态 stub
            return NodeResult(outputs={
                "chunks": [],
                "stub": f"[Dataset stub] dataset={dataset_id} query={str(query)[:80]}",
            })

        vector_store = ctx.services.get("vector_store")
        embedding_service = ctx.services.get("embedding")

        query_vec = await self._embed_one(embedding_service, str(query))

        try:
            results = await vector_store.search(
                dataset_id=dataset_id,
                query_vector=query_vec,
                top_k=top_k,
                tenant_id=str(ctx.env.tenant_id),
            )
        except Exception as exc:
            logger.exception("Dataset 检索失败: dataset=%s", dataset_id)
            raise RuntimeError(f"知识库检索失败: {exc}") from exc

        chunks = [
            {
                "content": r.chunk.content,
                "score": r.score,
                "metadata": r.chunk.metadata,
                "document_id": r.chunk.document_id,
            }
            for r in results
        ]
        return NodeResult(outputs={"chunks": chunks, "count": len(chunks)})

    async def _embed_one(self, embedding_service: Any, text: str) -> list[float]:
        vectors = await embedding_service.embed([text])
        if not vectors:
            raise RuntimeError("embedding 服务返回空向量")
        return list(vectors[0])


register_node_handler(DatasetNodeHandler())
