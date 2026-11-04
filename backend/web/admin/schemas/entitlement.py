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


class GrantApplicationPayload(BaseModel):
    """OPS 直开应用：start_time 必填（引擎据此判定 active/wait_effect），auth_source 服务端固定 OPS。"""

    tenant_id: UUID
    auth_type: Literal["FORMAL", "TRIAL", "GIFT"] = "FORMAL"
    contract_no: str = ""
    quota_json: dict[str, Any] = Field(default_factory=dict)
    start_time: datetime
    expire_time: datetime | None = None
    remark: str = ""


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


class GrantApplicationOut(BaseModel):
    """直开结果：新建授权行 ID。"""

    instance_id: UUID


class EntitlementTenantRowOut(BaseModel):
    """对象反查：持有该权益的租户行。"""

    tenant_id: UUID
    tenant_name: str
    status: str
    auth_source: str
    granted_at: datetime | None = None


class EntitlementPurgeRequest(BaseModel):
    """权益清除请求：不可逆物理删除，confirm 必须显式为 True（P3-6）。"""

    tenant_id: UUID
    object_type: EntitlementObjectType
    object_id: UUID
    reason: str = ""
    confirm: bool = False


class EntitlementPurgeOut(BaseModel):
    """清除结果：删除计数与审计快照记录 ID。"""

    deleted: int
    role_grants_deleted: int
    audit_id: UUID


class EntitlementPlanCreateRequest(BaseModel):
    """套餐模板创建请求：条目集合 + 默认 auth_type/期限/配额（P3-3）。"""

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    auth_type: Literal["FORMAL", "TRIAL", "GIFT"] = "FORMAL"
    duration_days: int | None = Field(None, ge=1, le=36500)
    quota: dict[str, Any] = Field(default_factory=dict)
    items: list[EntitlementItemIn] = Field(min_length=1, max_length=100)


class EntitlementPlanApplyRequest(BaseModel):
    """套餐开通请求：expire_time 缺省时按模板 duration_days 顺延。"""

    tenant_id: UUID
    reason: str = ""
    start_time: datetime | None = None
    expire_time: datetime | None = None


class EntitlementPlanItemOut(BaseModel):
    """模板条目视图（from_attributes 映射 EntitlementItem）。"""

    model_config = ConfigDict(from_attributes=True)

    object_type: str
    object_id: UUID


class EntitlementPlanOut(BaseModel):
    """套餐模板视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str
    auth_type: str
    duration_days: int | None
    quota: dict[str, Any]
    is_active: bool
    items: list[EntitlementPlanItemOut]
