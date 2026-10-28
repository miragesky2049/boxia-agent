"""知识库文档与分块领域实体。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID


@dataclass(frozen=True)
class Document:
    """知识库文档元数据。"""

    id: UUID
    title: str
    source_type: str
    source_uri: str
    raw_content: str
    content_hash: str
    ingest_status: str
    ingest_error: str
    chunk_count: int
    metadata: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID
    agent_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级知识库。"""
        return self.tenant_id == PLATFORM_TENANT_ID


@dataclass(frozen=True)
class DocumentChunk:
    """文档分块；embedding 由仓储/服务层填充，实体本身不强制要求。"""

    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    token_count: int
    created_at: datetime
    tenant_id: UUID
    embedding: list[float] | None = None
    # 结构化元数据：heading_path / source 等，检索结果拼装 prompt 时用
    metadata: dict[str, Any] = field(default_factory=dict)
    # 检索时由服务层填充的余弦相似度，非持久化字段
    score: float = field(default=0.0, compare=False)
    # rerank 分数（Cross-Encoder），未走 rerank 时为 None
    rerank_score: float | None = field(default=None, compare=False)
