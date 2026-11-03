"""权益统一读写模型：屏蔽 tenant_application_instance 与 resource_grant 两套存储。

视图状态在读侧按 UTC 左闭右开区间 [start_time, expire_time) 计算（D-3），
不依赖 Celery 定时任务的持久化 status 刷新，避免"已过期但仍可用"窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

OBJECT_TYPE_APP = "app"
ENTITLEMENT_OBJECT_TYPES: tuple[str, ...] = ("app", "tool", "skill", "prompt", "knowledge")

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_DISABLED = "disabled"
STATUS_REVOKED = "revoked"
STATUS_WAIT_EFFECT = "wait_effect"
STATUS_EXPIRED = "expired"

# 终态：时间不再参与计算，直接透出持久值（suspended/disabled 视为不可用）
_TERMINAL_STATUSES = frozenset({STATUS_REVOKED, STATUS_SUSPENDED, STATUS_DISABLED})


def effective_status(
    status: str,
    start_time: datetime | None,
    expire_time: datetime | None,
    now: datetime,
) -> str:
    """读侧生效判定：revoked/suspended/disabled 原样透出；其余按时间区间归一到三态。"""
    if status in _TERMINAL_STATUSES:
        return status
    if status == STATUS_EXPIRED:
        return STATUS_EXPIRED
    if start_time is not None and start_time > now:
        return STATUS_WAIT_EFFECT
    if expire_time is not None and expire_time <= now:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


@dataclass(frozen=True)
class EntitlementItem:
    """批量操作条目：一个对象（应用或资源）对当前租户的权益。"""

    object_type: str
    object_id: UUID

    def to_dict(self) -> dict[str, str]:
        """JSON 安全序列化，供审计 detail 使用。"""
        return {"object_type": self.object_type, "object_id": str(self.object_id)}


@dataclass(frozen=True)
class EntitlementView:
    """权益视图：status 为读侧时间计算后的有效状态。"""

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
    is_deprecated: bool = False


@dataclass(frozen=True)
class RemovePreviewItem:
    """revoke 预览项：附带受影响的角色授权（D-3 软失效语义）。"""

    view: EntitlementView
    affected_role_grants: int = 0
    affected_role_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchPreview:
    """dry-run 结果：不改库，仅给出将新增/将失效/无变化三组。"""

    add: tuple[EntitlementView, ...] = ()
    remove: tuple[RemovePreviewItem, ...] = ()
    unchanged: tuple[EntitlementView, ...] = ()


@dataclass(frozen=True)
class BatchResult:
    """apply_batch 结果：单事务，任一项校验失败整体不写入并返回 failed 明细。"""

    updated: int = 0
    failed: tuple[dict[str, Any], ...] = ()
    affected_role_grants: int = 0
