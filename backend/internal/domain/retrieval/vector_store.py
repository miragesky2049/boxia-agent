"""VectorStore 抽象接口：底层向量库（Milvus / PGVector / 其他）的统一契约。

节点 handler 只依赖本接口，不直接 import pymilvus / psycopg 等基础设施。
具体实现放在 internal/infrastructure/vector_store/ 下。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from internal.domain.retrieval.model import Chunk, DatasetConfig, RetrievalResult


class VectorStore(ABC):
    """向量库统一接口。

    方法命名对齐 coze retrieval provider：
    - create_dataset / drop_dataset: 集合生命周期
    - upsert / delete: 写入与删除
    - search: 向量近邻检索
    """

    @abstractmethod
    async def create_dataset(self, config: DatasetConfig) -> None:
        """创建向量集合（已存在则幂等返回）。"""

    @abstractmethod
    async def drop_dataset(self, dataset_id: str) -> None:
        """删除向量集合（含全部数据）。"""

    @abstractmethod
    async def upsert(self, chunks: list[Chunk]) -> None:
        """批量写入/更新向量（按 chunk_id 去重）。"""

    @abstractmethod
    async def delete(self, dataset_id: str, chunk_ids: list[str]) -> None:
        """按 chunk_id 批量删除。"""

    @abstractmethod
    async def search(
        self,
        dataset_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_expr: dict[str, Any] | None = None,
        tenant_id: str = "",
    ) -> list[RetrievalResult]:
        """向量近邻检索，返回 top_k 条命中。

        Args:
            dataset_id: 目标知识库
            query_vector: 查询向量（由 embedding 模型生成）
            top_k: 返回条数
            filter_expr: 元数据过滤条件（如 document_id / tag）
            tenant_id: 租户隔离命名空间
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """探活：向量库是否可用。"""
