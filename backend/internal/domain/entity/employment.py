"""用户任职记录领域实体。"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

# 用工性质枚举值；与迁移 0019 的 ck_emp_nature 约束保持一致。
EMPLOYMENT_NATURES = ("regular", "dispatch", "outsourced", "intern")

# 任职变动类型枚举值；与 ck_emp_change_type 约束保持一致。
EMPLOYMENT_CHANGE_TYPES = ("hire", "transfer", "promotion", "demotion", "reorganization")

# 离职类型枚举值；与 ck_emp_termination_type 约束保持一致。
TERMINATION_TYPES = ("resignation", "dismissal", "layoff", "retirement")


@dataclass(frozen=True)
class Employment:
    """任职记录；is_current 为真时对应用户的当前主任职，同一用户同时仅一条。"""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    department_id: UUID
    position: str
    is_current: bool
    started_at: date
    ended_at: date | None
    created_at: datetime
    updated_at: datetime
    # HR 字典外键
    employment_type_id: UUID | None = None
    job_level_id: UUID | None = None
    job_family_id: UUID | None = None
    # 汇报上级
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
    # 列表展示用冗余字段，由仓储 join 用户/部门/字典回填
    user_name: str | None = None
    user_display_name: str | None = None
    department_name: str | None = None
    department_path: str | None = None
    manager_name: str | None = None
    employment_type_name: str | None = None
    job_level_name: str | None = None
    job_family_name: str | None = None
