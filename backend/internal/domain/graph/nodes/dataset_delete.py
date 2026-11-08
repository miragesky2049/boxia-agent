"""数据集删除节点（知识库删除）：按 documentID 删除知识库中的文档。

config 约定：
- datasetId: 目标知识库

inputs:
- documentID / document_id: 待删除文档 ID

依赖服务：
- vector_store: 需实现 delete_by_document(dataset_id, document_id, tenant_id)
"""

from __future__ import annotations

import logging

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class DatasetDeleteNodeHandler(NodeHandler):
    """按文档 ID 删除知识库内容。"""

    type_name = NodeType.DATASET_DELETE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        dataset_id = str(config.get("datasetId") or config.get("dataset_id") or "")
        document_id = self._resolve_document_id(ctx)

        if not dataset_id:
            return NodeResult(outputs={"isSuccess": False, "error": "知识库删除节点缺少 datasetId"})
        if not document_id:
            return NodeResult(
                outputs={"isSuccess": False, "error": "知识库删除节点缺少 documentID"}
            )

        if not ctx.services.has("vector_store"):
            return NodeResult(
                outputs={
                    "isSuccess": True,
                    "stub": f"[DatasetDelete stub] dataset={dataset_id} document={document_id}",
                }
            )

        try:
            await ctx.services.get("vector_store").delete_by_document(
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=str(ctx.env.tenant_id),
            )
        except Exception as exc:
            logger.exception("知识库删除失败: dataset=%s document=%s", dataset_id, document_id)
            raise RuntimeError(f"知识库删除失败: {exc}") from exc

        return NodeResult(outputs={"isSuccess": True})

    @staticmethod
    def _resolve_document_id(ctx: NodeContext) -> str:
        for key in ("documentID", "document_id", "documentId"):
            value = ctx.inputs.get(key)
            if value:
                return str(value)
        for key in ("documentID", "document_id", "documentId"):
            value = (ctx.config or {}).get(key)
            if value:
                return str(value)
        return ""


register_node_handler(DatasetDeleteNodeHandler())
