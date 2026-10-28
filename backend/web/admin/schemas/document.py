"""知识库文档 schema。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentPayload(BaseModel):
    """创建文档入参：标题 + 内联文本 / markdown 内容。"""

    title: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="text", max_length=32)
    content: str = Field(default="", max_length=200_000)
    agent_id: UUID | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentOut(BaseModel):
    """文档出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None = None
    agent_id: UUID | None = None
    title: str
    source_type: str
    source_uri: str
    content_hash: str
    ingest_status: str
    ingest_error: str
    chunk_count: int
    metadata: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    is_platform: bool = False


class DocumentIngestResponse(BaseModel):
    """触发 ingest 的响应。"""

    document_id: UUID
    ingest_status: str
    chunk_count: int
