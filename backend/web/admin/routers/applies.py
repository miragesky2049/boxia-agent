"""申请单管理接口：运营审核 + 租户提交/查询。

- 租户侧：提交申请、查询我的申请列表
- 运营侧：待审核列表、认领、通过、拒绝
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.auth.apply_service import ApplyError, ApplyService, SubmitApplyRequest
from internal.domain.auth.grant_service import GrantError, GrantService
from internal.domain.auth.service import AuthService
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from web.deps.auth import AdminAuthDep, PlatformAdminDep
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/applies", tags=["applies"])


def _build_apply_service(uow: UowDep) -> ApplyService:
    repo = AuthRepository(uow.session)
    auth_service = AuthService(repo, cache=None)
    grant_service = GrantService(repo, auth_service)
    return ApplyService(repo, auth_service, grant_service)


ApplyServiceDep = Annotated[ApplyService, Depends(_build_apply_service)]


# ========== 租户侧：提交申请 ==========
class SubmitApplyPayload(BaseModel):
    application_id: UUID
    apply_type: str = Field(..., description="TRIAL / BUY")
    expect_text: str = ""
    contact: str = Field(..., max_length=200)


@router.post("", status_code=201)
def submit_apply(
    payload: SubmitApplyPayload,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
    service: ApplyServiceDep,
) -> dict:
    """租户提交应用申请。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    try:
        apply_id = service.submit(SubmitApplyRequest(
            tenant_id=tenant_id,
            application_id=payload.application_id,
            apply_type=payload.apply_type,
            expect_text=payload.expect_text,
            contact=payload.contact,
            created_by=principal.user_id,
        ))
    except ApplyError as exc:
        raise ValidationError(str(exc)) from exc
    uow.commit()
    return {"id": str(apply_id)}


@router.get("/mine")
def list_my_applies(
    uow: UowDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户查看自己的申请记录。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return AuthRepository(uow.session).list_apply_by_tenant(tenant_id)


# ========== 运营侧：待审核列表 ==========
@router.get("/pass-pending")
def list_pass_pending(uow: UowDep) -> list[dict]:
    """运营查看待开通（PASS 状态）的申请单。"""
    return AuthRepository(uow.session).list_pass_pending_apply()


@router.get("/sales-mine")
def list_sales_mine(
    uow: UowDep,
    principal: AdminAuthDep,
) -> list[dict]:
    """销售查看归属自己的申请单。"""
    return AuthRepository(uow.session).list_apply_by_sales(principal.user_id)


# ========== 运营侧：认领 ==========
@router.post("/{apply_id}/claim")
def claim_apply(
    apply_id: UUID,
    uow: UowDep,
    principal: AdminAuthDep,
    service: ApplyServiceDep,
) -> dict:
    """销售认领申请单。"""
    try:
        service.claim(apply_id, principal.user_id, principal.username)
    except ApplyError as exc:
        raise ValidationError(str(exc)) from exc
    uow.commit()
    return {"ok": True}


# ========== 运营侧：通过 ==========
class PassApplyPayload(BaseModel):
    audit_msg: str = ""
    contract_no: str = ""
    # 若提供则同时开通授权
    grant_start_time: datetime | None = None
    grant_expire_time: datetime | None = None
    grant_quota: dict[str, Any] | None = None


@router.post("/{apply_id}/pass")
async def pass_apply(
    apply_id: UUID,
    payload: PassApplyPayload,
    uow: UowDep,
    principal: AdminAuthDep,
    service: ApplyServiceDep,
) -> dict:
    """审核通过申请单，可选同时开通授权。"""
    from internal.domain.auth.apply_service import PassApplyRequest
    try:
        instance_id = await service.pass_apply(PassApplyRequest(
            apply_id=apply_id,
            operator_id=principal.user_id,
            operator_name=principal.username,
            audit_msg=payload.audit_msg,
            contract_no=payload.contract_no,
            grant_start_time=payload.grant_start_time,
            grant_expire_time=payload.grant_expire_time,
            grant_quota=payload.grant_quota,
        ))
    except (ApplyError, GrantError) as exc:
        raise ValidationError(str(exc)) from exc
    uow.commit()
    return {
        "ok": True,
        "instance_id": str(instance_id) if instance_id else None,
    }


# ========== 运营侧：拒绝 ==========
class RejectApplyPayload(BaseModel):
    audit_msg: str = Field(..., description="拒绝原因")


@router.post("/{apply_id}/reject")
def reject_apply(
    apply_id: UUID,
    payload: RejectApplyPayload,
    uow: UowDep,
    principal: AdminAuthDep,
    service: ApplyServiceDep,
) -> dict:
    """拒绝申请单。"""
    try:
        service.reject(apply_id, payload.audit_msg, principal.user_id, principal.username)
    except ApplyError as exc:
        raise ValidationError(str(exc)) from exc
    uow.commit()
    return {"ok": True}


# ========== 运营工作台：待审核队列 + 仪表盘 ==========
@router.get("/ops/pending")
def list_ops_pending(
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> list[dict]:
    """运营工作台：待审核申请队列（SUBMITTED/HANDLING），按提交时间升序。"""
    return AuthRepository(uow.session).list_pending_applies()


@router.get("/ops/dashboard")
def ops_dashboard(
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> dict:
    """运营工作台仪表盘：各状态申请数 + 授权数统计。"""
    return AuthRepository(uow.session).ops_dashboard_stats()
