"""套餐模板实体：条目集合 + 默认 auth_type/期限/配额（P3-3）。

模板是平台级定义（不区分租户），开通时展开为批量条目复用 apply_batch，
权益行仍落 tenant_application_instance / tenant_resource_entitlement 双表，模板本身不落权益。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from internal.domain.entity.entitlement import EntitlementItem

PLAN_AUTH_TYPES: tuple[str, ...] = ("FORMAL", "TRIAL", "GIFT")


@dataclass(frozen=True)
class EntitlementPlan:
    """套餐模板：items 为将批量开通的对象条目集合。"""

    id: UUID
    code: str
    name: str
    description: str
    auth_type: str
    duration_days: int | None
    quota: dict[str, Any]
    is_active: bool
    items: tuple[EntitlementItem, ...] = ()
