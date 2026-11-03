"""权益管理请求/响应模型（产品级 /admin/entitlements，P1-6）。"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EntitlementObjectType = Literal["app", "tool", "skill", "prompt", "knowledge"]


class EntitlementItemIn(BaseModel):
    """批量操作条目：一个对象（应用或资源）。"""

    object_type: EntitlementObjectType
    object_id: UUID


class EntitlementBatchRequest(BaseModel):
    """批量开通/取消请求；items 上限 100（服务层另有 200 兜底）。"""

    tenant_id: UUID
    mode: Literal["grant", "revoke"]
    items: list[EntitlementItemIn] = Field(min_length=1, max_length=100)
    reason: str = ""
    auth_type: Literal["FORMAL", "TRIAL", "GIFT"] = "FORMAL"
    start_time: datetime | None = None
    expire_time: datetime | None = None


class EntitlementViewOut(BaseModel):
    """权益视图；status 为读侧时间计算后的有效状态。"""

    model_config = ConfigDict(from_attributes=True)

    object_type: str
    object_id: UUID
    name: str
    status: str
    auth_source: str
    auth_type: str
    start_time: datetime | None
    expire_time: datetime | None
    quota: dict[str, Any]
    remark: str
    granted_at: datetime | None
    is_deprecated: bool


class RemovePreviewOut(BaseModel):
    """revoke 预览项：附带受影响的角色授权（D-3 软失效提示）。"""

    model_config = ConfigDict(from_attributes=True)

    view: EntitlementViewOut
    affected_role_grants: int
    affected_role_names: list[str]


class EntitlementPreviewOut(BaseModel):
    """dry-run 三组分类结果。"""

    model_config = ConfigDict(from_attributes=True)

    add: list[EntitlementViewOut]
    remove: list[RemovePreviewOut]
    unchanged: list[EntitlementViewOut]


class EntitlementBatchOut(BaseModel):
    """批量结果；revoke 时 affected_role_grants 为软失效影响的角色授权数。"""

    updated: int
    failed: list[dict[str, Any]] = Field(default_factory=list)
    affected_role_grants: int = 0


class EntitlementTenantRowOut(BaseModel):
    """对象反查：持有该权益的租户行。"""

    tenant_id: UUID
    tenant_name: str
    status: str
    auth_source: str
    granted_at: datetime | None = None
