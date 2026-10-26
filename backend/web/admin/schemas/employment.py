"""用户任职记录请求/响应模型。"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmploymentOut(BaseModel):
    """任职记录，含用户与部门展示字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    department_id: UUID
    position: str
    is_current: bool
    started_at: date
    ended_at: date | None
    user_name: str | None = None
    user_display_name: str | None = None
    department_name: str | None = None
    department_path: str | None = None
    created_at: datetime
    updated_at: datetime


class EmploymentCreateRequest(BaseModel):
    """新增当前任职请求。"""

    user_id: UUID
    department_id: UUID
    position: str = Field(default="", max_length=100)
    started_at: date | None = None


class EmploymentUpdateRequest(BaseModel):
    """更新任职岗位/生效日期请求，部门变更请走调岗。"""

    position: str | None = Field(default=None, max_length=100)
    started_at: date | None = None


class EmploymentTransferRequest(BaseModel):
    """调岗请求；生效日期缺省为今天，岗位缺省沿用原岗位。"""

    department_id: UUID
    position: str | None = Field(default=None, max_length=100)
    started_at: date | None = None


class EmploymentArchiveRequest(BaseModel):
    """结束任职请求；结束日期缺省为今天。"""

    ended_at: date | None = None
