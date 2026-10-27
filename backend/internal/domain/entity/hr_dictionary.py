"""HR 字典领域实体：雇佣类型、岗位职级、岗位序列等租户级字典。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# 字典类别清单；与迁移 0019 中的 CHECK 约束保持一致。
HR_DICTIONARY_CATEGORIES = ("employment_type", "job_level", "job_family")


@dataclass(frozen=True)
class HrDictionary:
    """HR 字典项；category 区分字典类别，同一租户内 code 唯一。"""

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
