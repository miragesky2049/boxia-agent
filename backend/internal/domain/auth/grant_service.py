"""授权变更服务：开通 / 回收。

核心规则（MVP）：
1. 同一 (tenant_id, app_id) 同时只允许 1 条 ACTIVE 授权
2. 所有变更写 audit_logs，物理不删除
3. 变更后主动失效 Redis 缓存
4. start_time < now 直接 ACTIVE；未来时间走 WAIT_EFFECT
5. expire_time < now 禁止新增 FORMAL 授权

基于复用现有表的设计：
- tenant_application_instance 存授权记录
- application_apply 存申请单
- audit_logs 存审计日志
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from internal.domain.auth.service import AuthService
from internal.domain.entity.auth_constants import (
    AuthOperation,
    AuthSource,
    AuthStatus,
    AuthType,
    ApplyStatus,
)

logger = logging.getLogger(__name__)


class GrantError(Exception):
    """授权变更业务异常。"""


@dataclass(frozen=True)
class CreateGrantRequest:
    tenant_id: UUID
    app_id: UUID
    auth_type: str
    contract_no: str
    quota_json: dict[str, Any]
    start_time: datetime
    expire_time: datetime | None
    remark: str = ""
    auth_source: str = AuthSource.OPS.value
    apply_id: UUID | None = None
    operator_id: UUID | None = None
    operator_name: str = ""


class GrantService:
    """授权开通 / 回收领域服务。"""

    def __init__(
        self,
        auth_repo: Any,
        auth_service: AuthService,
    ) -> None:
        self._auth_repo = auth_repo
        self._auth = auth_service

    async def create_grant(self, req: CreateGrantRequest) -> UUID:
        """新增授权（链路 A 运营开通 + 链路 B 关联申请单开通共用）。

        Returns:
            新建授权的 instance_id
        """
        self._validate(req)

        # MVP 规则：同一 tenant+app 已有 ACTIVE 则拒绝
        if self._auth_repo.exists_active_grant(req.tenant_id, req.app_id):
            raise GrantError("当前租户对该应用已有 ACTIVE 授权，请先回收旧授权")

        status = self._initial_status(req.start_time)

        instance_id = self._auth_repo.create_grant({
            "tenant_id": req.tenant_id,
            "application_id": req.app_id,
            "status": status,
            "source": "granted" if req.auth_source == AuthSource.OPS.value else "marketplace",
            "auth_source": req.auth_source,
            "auth_type": req.auth_type,
            "contract_no": req.contract_no,
            "quota_json": req.quota_json,
            "start_time": req.start_time,
            "expire_time": req.expire_time,
            "apply_id": req.apply_id,
            "remark": req.remark,
            "granted_by": req.operator_id,
            "granted_at": datetime.now(timezone.utc),
        })

        # 写审计日志（复用 audit_logs 表）
        self._auth_repo.append_audit_log({
            "tenant_id": req.tenant_id,
            "actor_id": req.operator_id,
            "actor_username": req.operator_name,
            "action": AuthOperation.CREATE.value,
            "resource_type": "tenant_application_instance",
            "resource_id": str(instance_id),
            "detail": {
                "before": None,
                "after": self._snapshot({
                    "id": instance_id,
                    "tenant_id": req.tenant_id,
                    "app_id": req.app_id,
                    "auth_type": req.auth_type,
                    "status": status,
                    "contract_no": req.contract_no,
                    "quota_json": req.quota_json,
                    "start_time": req.start_time,
                    "expire_time": req.expire_time,
                }),
                "remark": req.remark,
            },
        })

        # 关联申请单开通：把申请单状态推进到 FINISH
        if req.apply_id is not None:
            self._auth_repo.update_apply_status(
                req.apply_id,
                ApplyStatus.FINISH.value,
            )
            self._auth_repo.append_audit_log({
                "tenant_id": req.tenant_id,
                "actor_id": req.operator_id,
                "actor_username": req.operator_name,
                "action": AuthOperation.APPLY_FINISH.value,
                "resource_type": "application_apply",
                "resource_id": str(req.apply_id),
                "detail": {
                    "before": {"status": ApplyStatus.PASS.value},
                    "after": {"status": ApplyStatus.FINISH.value},
                },
            })

        # 清缓存
        await self._auth.invalidate(req.tenant_id, req.app_id)

        logger.info("授权已创建: tenant=%s app=%s status=%s", req.tenant_id, req.app_id, status)
        return instance_id

    async def recycle_grant(
        self,
        instance_id: UUID,
        operator_id: UUID | None,
        operator_name: str,
        reason: str = "",
    ) -> None:
        """回收授权：ACTIVE/WAIT_EFFECT → revoked。"""
        record = self._auth_repo.get_grant(instance_id)
        if record is None:
            raise GrantError("授权记录不存在")
        if record["status"] == "revoked":
            raise GrantError("授权已处于回收状态")

        before = self._snapshot(record)
        self._auth_repo.update_grant_status(instance_id, "revoked")

        self._auth_repo.append_audit_log({
            "tenant_id": record["tenant_id"],
            "actor_id": operator_id,
            "actor_username": operator_name,
            "action": AuthOperation.RECYCLE.value,
            "resource_type": "tenant_application_instance",
            "resource_id": str(instance_id),
            "detail": {
                "before": before,
                "after": {"status": "revoked"},
                "reason": reason,
            },
        })
        await self._auth.invalidate(record["tenant_id"], record["application_id"])

    async def process_wait_effective(self) -> int:
        """定时任务：把已到 start_time 的 wait_effect 记录转为 active。

        Returns:
            本次激活的授权数
        """
        now = datetime.now(timezone.utc)
        rows = self._auth_repo.list_wait_effective(now)
        for row in rows:
            instance_id = row["id"]
            before = self._snapshot(row)
            self._auth_repo.update_grant_status(instance_id, "active")
            self._auth_repo.append_audit_log({
                "tenant_id": row["tenant_id"],
                "actor_id": None,
                "actor_username": "system",
                "action": AuthOperation.ACTIVATE.value,
                "resource_type": "tenant_application_instance",
                "resource_id": str(instance_id),
                "detail": {
                    "before": before,
                    "after": {"status": "active"},
                    "reason": "定时任务：到点自动激活",
                },
            })
            await self._auth.invalidate(row["tenant_id"], row["application_id"])
        if rows:
            logger.info("定时激活授权: %d 条", len(rows))
        return len(rows)

    async def process_expired(self) -> int:
        """定时任务：把已过 expire_time 的 active 记录转为 expired。

        Returns:
            本次过期的授权数
        """
        now = datetime.now(timezone.utc)
        rows = self._auth_repo.list_expired(now)
        for row in rows:
            instance_id = row["id"]
            before = self._snapshot(row)
            self._auth_repo.update_grant_status(instance_id, "expired")
            self._auth_repo.append_audit_log({
                "tenant_id": row["tenant_id"],
                "actor_id": None,
                "actor_username": "system",
                "action": AuthOperation.EXPIRE.value,
                "resource_type": "tenant_application_instance",
                "resource_id": str(instance_id),
                "detail": {
                    "before": before,
                    "after": {"status": "expired"},
                    "reason": "定时任务：到期自动过期",
                },
            })
            await self._auth.invalidate(row["tenant_id"], row["application_id"])
        if rows:
            logger.info("定时过期授权: %d 条", len(rows))
        return len(rows)

    def _validate(self, req: CreateGrantRequest) -> None:
        if req.auth_type not in {t.value for t in AuthType}:
            raise GrantError(f"非法 auth_type: {req.auth_type}")
        if req.auth_source not in {s.value for s in AuthSource}:
            raise GrantError(f"非法 auth_source: {req.auth_source}")

        now = datetime.now(timezone.utc)
        # 异常规则 2：expire_time 小于当前时间禁止新增 FORMAL
        if req.auth_type == AuthType.FORMAL.value and req.expire_time is not None and req.expire_time <= now:
            raise GrantError("正式授权的 expire_time 不能早于当前时间")

    @staticmethod
    def _initial_status(start_time: datetime) -> str:
        now = datetime.now(timezone.utc)
        # 规则 1：start_time 已过 → 直接 active；未来时间走 wait_effect
        if start_time <= now:
            return "active"
        return "wait_effect"

    @staticmethod
    def _snapshot(record: dict[str, Any]) -> dict[str, Any]:
        """统一快照格式。"""
        return {
            "id": str(record.get("id", "")),
            "tenant_id": str(record.get("tenant_id", "")),
            "app_id": str(record.get("application_id", record.get("app_id", ""))),
            "auth_type": record.get("auth_type", ""),
            "status": record.get("status", ""),
            "contract_no": record.get("contract_no", ""),
            "quota_json": dict(record.get("quota_json") or {}),
            "start_time": record.get("start_time", "").isoformat() if record.get("start_time") else None,
            "expire_time": record.get("expire_time", "").isoformat() if record.get("expire_time") else None,
        }
