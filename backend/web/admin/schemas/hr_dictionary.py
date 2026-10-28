"""HR 字典请求/响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HrDictionaryOut(BaseModel):
    """HR 字典项响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    category: str
    code: str
    name: str
    sort_order: int
    is_active: bool
    remark: str
    created_at: datetime
    updated_at: datetime


class HrDictionaryCreateRequest(BaseModel):
    """新建字典项请求。"""

    category: str = Field(..., min_length=1, max_length=32)
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=9999)
    remark: str = Field(default="", max_length=255)


class HrDictionaryUpdateRequest(BaseModel):
    """更新字典项请求；编码与类别不可改。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=255)
