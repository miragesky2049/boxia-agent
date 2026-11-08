"""DatasetWrite 节点（coze type=27）：把文本写入知识库（向量化 + upsert）。

config 约定：
- datasetId: 目标知识库

inputs:
- content: 待写入文本
- metadata: 可选元数据 dict
- chunkId: 可选 chunk 主键（不传则由调用方生成）

依赖服务：
- embedding: 文本 → 向量
- vector_store: VectorStore 实例
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class DatasetWriteNodeHandler(NodeHandler):
    type_name = NodeType.DATASET_WRITE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        dataset_id = str(config.get("datasetId") or "")
        content = ctx.inputs.get("content")
        metadata = ctx.inputs.get("metadata") or {}
        chunk_id = str(ctx.inputs.get("chunkId") or uuid.uuid4())
        document_id = str(
            ctx.inputs.get("documentId")
            or ctx.inputs.get("document_id")
            or metadata.get("document_id")
            or ""
        )

        if not dataset_id:
            return NodeResult(
                outputs={"isSuccess": False, "error": "dataset_write 节点缺少 datasetId"}
            )
        if content is None:
            return NodeResult(
                outputs={"isSuccess": False, "error": "dataset_write 节点缺少 content"}
            )

        if not ctx.services.has("vector_store") or not ctx.services.has("embedding"):
            return NodeResult(
                outputs={
                    "chunkId": chunk_id,
                    "isSuccess": True,
                    "stub": f"[DatasetWrite stub] dataset={dataset_id}",
                }
            )

        vector_store = ctx.services.get("vector_store")
        embedding_service = ctx.services.get("embedding")

        vector = await self._embed_one(embedding_service, str(content))

        from internal.domain.retrieval.model import Chunk

        chunk = Chunk(
            chunk_id=chunk_id,
            content=str(content),
            dataset_id=dataset_id,
            document_id=document_id,
            metadata={**metadata, "_tenant_id": str(ctx.env.tenant_id)},
            vector=vector,
        )

        try:
            await vector_store.upsert([chunk])
        except Exception as exc:
            logger.exception("DatasetWrite 写入失败: dataset=%s", dataset_id)
            raise RuntimeError(f"知识库写入失败: {exc}") from exc

        return NodeResult(outputs={"chunkId": chunk_id, "isSuccess": True, "success": True})

    async def _embed_one(self, embedding_service: Any, text: str) -> list[float]:
        vectors = await embedding_service.embed([text])
        if not vectors:
            raise RuntimeError("embedding 服务返回空向量")
        return list(vectors[0])


register_node_handler(DatasetWriteNodeHandler())
