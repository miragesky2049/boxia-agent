"""申请单领域服务：提交 / 认领 / 审核通过 / 拒绝 / 关联开通。

状态机：
  SUBMITTED → HANDLING → PASS → (开通) → FINISH
                       ↘ REJECT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from internal.domain.auth.grant_service import GrantService
from internal.domain.auth.service import AuthService
from internal.domain.entity.auth_constants import (
    ApplyStatus,
    ApplyType,
    AuthOperation,
)

logger = logging.getLogger(__name__)


class ApplyError(Exception):
    """申请单业务异常。"""


@dataclass(frozen=True)
class SubmitApplyRequest:
    tenant_id: UUID
    application_id: UUID
    apply_type: str  # TRIAL / BUY
    expect_text: str
    contact: str
    created_by: UUID | None = None


@dataclass(frozen=True)
class PassApplyRequest:
    apply_id: UUID
    operator_id: UUID | None = None
    operator_name: str = ""
    audit_msg: str = ""
    contract_no: str = ""
    # 通过后是否立即开通授权
    grant_start_time: Any = None
    grant_expire_time: Any = None
    grant_quota: dict[str, Any] | None = None


class ApplyService:
    """申请单领域服务。"""

    def __init__(
        self,
        auth_repo: Any,
        auth_service: AuthService,
        grant_service: GrantService,
    ) -> None:
        self._repo = auth_repo
        self._auth = auth_service
        self._grants = grant_service

    # ========== 租户侧：提交申请 ==========
    def submit(self, req: SubmitApplyRequest) -> UUID:
        if req.apply_type not in {t.value for t in ApplyType}:
            raise ApplyError(f"非法 apply_type: {req.apply_type}")

        # 已有 ACTIVE 授权不允许再申请
        if self._repo.exists_active_grant(req.tenant_id, req.application_id):
            raise ApplyError("当前租户对该应用已有 ACTIVE 授权，无需重复申请")

        apply_id = self._repo.create_apply(
            {
                "tenant_id": req.tenant_id,
                "application_id": req.application_id,
                "apply_type": req.apply_type,
                "status": ApplyStatus.SUBMITTED.value,
                "expect_text": req.expect_text,
                "contact": req.contact,
                "sales_user_id": None,
                "created_by": req.created_by,
            }
        )

        self._repo.append_audit_log(
            {
                "tenant_id": req.tenant_id,
                "actor_id": req.created_by,
                "actor_username": "",
                "action": AuthOperation.APPLY_SUBMIT.value,
                "resource_type": "application_apply",
                "resource_id": str(apply_id),
                "detail": {
                    "before": None,
                    "after": {"status": ApplyStatus.SUBMITTED.value},
                },
            }
        )
        logger.info(
            "申请单已提交: id=%s tenant=%s app=%s", apply_id, req.tenant_id, req.application_id
        )
        return apply_id

    # ========== 销售/运营侧：认领申请单 ==========
    def claim(self, apply_id: UUID, sales_user_id: UUID, operator_name: str) -> None:
        row = self._repo.get_apply(apply_id)
        if row is None:
            raise ApplyError("申请单不存在")
        if row["status"] != ApplyStatus.SUBMITTED.value:
            raise ApplyError(f"仅 SUBMITTED 状态可认领，当前状态: {row['status']}")

        before = {"status": row["status"], "sales_user_id": row.get("sales_user_id")}
        # CAS 认领：状态在读取后被他人抢先变更时 rowcount=0，避免覆盖归属
        if not self._repo.claim_apply(apply_id, sales_user_id):
            raise ApplyError("申请单状态已变更，请刷新后重试")
        self._repo.append_audit_log(
            {
                "tenant_id": row["tenant_id"],
                "actor_id": sales_user_id,
                "actor_username": operator_name,
                "action": AuthOperation.APPLY_HANDLING.value,
                "resource_type": "application_apply",
                "resource_id": str(apply_id),
                "detail": {
                    "before": before,
                    "after": {
                        "status": ApplyStatus.HANDLING.value,
                        "sales_user_id": str(sales_user_id),
                    },
                },
            }
        )

    # ========== 运营侧：审核通过 ==========
    async def pass_apply(self, req: PassApplyRequest) -> UUID | None:
        """审核通过申请单。

        若提供了 grant 参数，则同时开通授权（FINISH）；否则仅置为 PASS 等待运营在
        「待开通」列表中单独开通。

        Returns:
            若直接开通，返回 instance_id；否则返回 None
        """
        row = self._repo.get_apply(req.apply_id)
        if row is None:
            raise ApplyError("申请单不存在")
        if row["status"] not in {ApplyStatus.SUBMITTED.value, ApplyStatus.HANDLING.value}:
            raise ApplyError(f"当前状态不可通过审核: {row['status']}")

        before = {"status": row["status"]}
        self._repo.update_apply_status(
            req.apply_id,
            ApplyStatus.PASS.value,
            audit_msg=req.audit_msg,
            contract_no=req.contract_no,
        )

        self._repo.append_audit_log(
            {
                "tenant_id": row["tenant_id"],
                "actor_id": req.operator_id,
                "actor_username": req.operator_name,
                "action": AuthOperation.APPLY_PASS.value,
                "resource_type": "application_apply",
                "resource_id": str(req.apply_id),
                "detail": {
                    "before": before,
                    "after": {"status": ApplyStatus.PASS.value},
                    "audit_msg": req.audit_msg,
                },
            }
        )

        # 若同时提供了开通参数，直接开通授权
        if req.grant_start_time is not None:
            from internal.domain.auth.grant_service import CreateGrantRequest

            grant_req = CreateGrantRequest(
                tenant_id=row["tenant_id"],
                app_id=row["application_id"],
                auth_type="TRIAL" if row["apply_type"] == ApplyType.TRIAL.value else "FORMAL",
                contract_no=req.contract_no or row.get("contract_no") or "",
                quota_json=req.grant_quota or {},
                start_time=req.grant_start_time,
                expire_time=req.grant_expire_time,
                apply_id=req.apply_id,
                operator_id=req.operator_id,
                operator_name=req.operator_name,
            )
            return await self._grants.create_grant(grant_req)
        return None

    # ========== 运营侧：拒绝申请 ==========
    def reject(
        self, apply_id: UUID, audit_msg: str, operator_id: UUID | None, operator_name: str
    ) -> None:
        row = self._repo.get_apply(apply_id)
        if row is None:
            raise ApplyError("申请单不存在")
        if row["status"] not in {ApplyStatus.SUBMITTED.value, ApplyStatus.HANDLING.value}:
            raise ApplyError(f"当前状态不可拒绝: {row['status']}")

        before = {"status": row["status"]}
        self._repo.update_apply_status(apply_id, ApplyStatus.REJECT.value, audit_msg=audit_msg)

        self._repo.append_audit_log(
            {
                "tenant_id": row["tenant_id"],
                "actor_id": operator_id,
                "actor_username": operator_name,
                "action": AuthOperation.APPLY_REJECT.value,
                "resource_type": "application_apply",
                "resource_id": str(apply_id),
                "detail": {
                    "before": before,
                    "after": {"status": ApplyStatus.REJECT.value},
                    "audit_msg": audit_msg,
                },
            }
        )

    # ========== 只读查询透传（五期从 applies / marketplace router 直构仓储收口） ==========
    def list_apply_by_tenant(self, tenant_id: UUID) -> list[dict]:
        """租户查看自己的申请记录。"""
        return self._repo.list_apply_by_tenant(tenant_id)

    def list_pass_pending_apply(self) -> list[dict]:
        """运营查看待开通（PASS 状态）的申请单。"""
        return self._repo.list_pass_pending_apply()

    def list_apply_by_sales(self, sales_user_id: UUID) -> list[dict]:
        """销售查看归属自己的申请单。"""
        return self._repo.list_apply_by_sales(sales_user_id)

    def list_pending_applies(self) -> list[dict]:
        """运营工作台待审核队列（SUBMITTED/HANDLING），按提交时间升序。"""
        return self._repo.list_pending_applies()

    def ops_dashboard_stats(self) -> dict[str, Any]:
        """运营工作台仪表盘：各状态申请数 + 授权数统计。"""
        return self._repo.ops_dashboard_stats()

    def get_latest_apply(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """租户对某应用的最近一条申请单（市场详情页状态卡片用）。"""
        return self._repo.get_latest_apply(tenant_id, application_id)
