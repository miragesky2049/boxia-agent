"""检索领域模型：知识库 / 文档块 / 检索结果。

对齐 coze retrieval 层核心概念：
- Dataset: 一个独立向量集合，绑定 embedding 模型与维度
- Chunk: 文档切分后的块，对应一条向量
- RetrievalResult: 单条检索命中（chunk + 相似度分数）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """知识库中的一个文档块（对应一条向量）。"""

    chunk_id: str
    content: str
    dataset_id: str
    document_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(frozen=True)
class RetrievalResult:
    """单条检索命中。"""

    chunk: Chunk
    score: float


@dataclass(frozen=True)
class DatasetConfig:
    """知识库配置：向量集合元信息。

    Attributes:
        dataset_id: 知识库唯一标识
        display_name: 知识库名称
        dimension: 向量维度（与 embedding 模型对齐）
        metric: 相似度度量（cosine / ip / l2）
        tenant_id: 多租户隔离命名空间
        embedding_model: 生成该向量集所用的 embedding 模型名
    """

    dataset_id: str
    display_name: str
    dimension: int
    metric: str = "cosine"
    tenant_id: str = ""
    embedding_model: str = ""
