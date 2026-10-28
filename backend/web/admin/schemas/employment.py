"""用户任职记录请求/响应模型。"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmploymentOut(BaseModel):
    """任职记录，含用户、部门、汇报上级与 HR 字典展示字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    department_id: UUID
    position: str
    is_current: bool
    started_at: date
    ended_at: date | None
    # HR 字典外键
    employment_type_id: UUID | None = None
    job_level_id: UUID | None = None
    job_family_id: UUID | None = None
    manager_id: UUID | None = None
    # 用工基础信息
    work_location: str | None = None
    cost_center: str | None = None
    contract_no: str | None = None
    weekly_hours: float | None = None
    employment_nature: str | None = None
    # 试用期与转正
    probation_started_at: date | None = None
    probation_ended_at: date | None = None
    regularized_at: date | None = None
    # 变动与离职
    change_type: str | None = None
    change_reason: str | None = None
    termination_type: str | None = None
    remark: str = ""
    # 展示字段
    user_name: str | None = None
    user_display_name: str | None = None
    department_name: str | None = None
    department_path: str | None = None
    manager_name: str | None = None
    employment_type_name: str | None = None
    job_level_name: str | None = None
    job_family_name: str | None = None
    created_at: datetime
    updated_at: datetime


class _HrFieldsMixin(BaseModel):
    """HR 字段公共入参；create / update / transfer 共用。"""

    employment_type_id: UUID | None = None
    job_level_id: UUID | None = None
    job_family_id: UUID | None = None
    manager_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=100)
    cost_center: str | None = Field(default=None, max_length=64)
    contract_no: str | None = Field(default=None, max_length=64)
    weekly_hours: float | None = Field(default=None, ge=0, le=168)
    employment_nature: str | None = None
    probation_started_at: date | None = None
    probation_ended_at: date | None = None
    regularized_at: date | None = None
    change_reason: str | None = Field(default=None, max_length=255)
    remark: str | None = None


class EmploymentCreateRequest(_HrFieldsMixin):
    """新增当前任职请求。"""

    user_id: UUID
    department_id: UUID
    position: str = Field(default="", max_length=100)
    started_at: date | None = None


class EmploymentUpdateRequest(_HrFieldsMixin):
    """更新任职岗位/生效日期与 HR 字段请求，部门变更请走调岗。"""

    position: str | None = Field(default=None, max_length=100)
    started_at: date | None = None


class EmploymentTransferRequest(_HrFieldsMixin):
    """调岗请求；生效日期缺省为今天，岗位缺省沿用原岗位。

    未在 HrFieldsMixin 中显式传入的字段将沿用原任职记录；显式传 null 表示清空。
    """

    department_id: UUID
    position: str | None = Field(default=None, max_length=100)
    started_at: date | None = None
    change_type: str = "transfer"


class EmploymentArchiveRequest(BaseModel):
    """结束任职请求；结束日期缺省为今天。"""

    ended_at: date | None = None
    termination_type: str | None = None
    change_reason: str | None = Field(default=None, max_length=255)
