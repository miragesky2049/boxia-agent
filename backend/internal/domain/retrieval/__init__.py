"""检索领域层：向量库抽象与知识库模型。"""

from internal.domain.retrieval.model import Chunk, DatasetConfig, RetrievalResult
from internal.domain.retrieval.vector_store import VectorStore

__all__ = ["Chunk", "DatasetConfig", "RetrievalResult", "VectorStore"]
