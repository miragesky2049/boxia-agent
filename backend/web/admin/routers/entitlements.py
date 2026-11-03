"""产品级权益管理入口：应用与四类资源对租户的统一开通/取消（P1-6/P1-7）。

全局依赖 require_platform_admin：租户作用域访问一律 403（SCOPE_FORBIDDEN）；
router 只做参数收窄与 DTO 转换，两套存储差异全部收口在 EntitlementService。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from internal.application.errors import ValidationError
from internal.domain.auth.grant_service import CreateGrantRequest, GrantError
from internal.domain.entity.entitlement import EntitlementItem
from web.admin.schemas.common import PageOut
from web.admin.schemas.entitlement import (
    EntitlementBatchOut,
    EntitlementBatchRequest,
    EntitlementPlanApplyRequest,
    EntitlementPlanCreateRequest,
    EntitlementPlanOut,
    EntitlementPreviewOut,
    EntitlementPurgeOut,
    EntitlementPurgeRequest,
    EntitlementTenantRowOut,
    EntitlementViewOut,
    GrantApplicationOut,
    GrantApplicationPayload,
)
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
from web.deps.db import UowDep
from web.deps.entitlement_services import EntitlementServiceDep, GrantEngineServiceDep
from web.deps.http import client_meta

router = APIRouter(
    prefix="/entitlements",
    tags=["admin-entitlements"],
    dependencies=[Depends(require_platform_admin)],
)

_VIEW_ENTITLEMENTS = Depends(require_permission("page:entitlements"))
_MANAGE_ENTITLEMENTS = Depends(require_permission("button:entitlement:manage"))


@router.get(
    "/tenants/{tenant_id}",
    response_model=PageOut[EntitlementViewOut],
    dependencies=[_VIEW_ENTITLEMENTS],
)
def list_tenant_entitlements(
    tenant_id: UUID,
    service: EntitlementServiceDep,
    object_type: str | None = Query(None, max_length=16),
    status: str | None = Query(None, max_length=16),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PageOut[EntitlementViewOut]:
    """租户权益分页：五类对象统一视图，status 为时间计算后的有效状态。"""
    result = service.list_by_tenant(
        tenant_id,
        object_type=object_type,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return PageOut[EntitlementViewOut](
        items=[EntitlementViewOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/objects/{object_type}/{object_id}/tenants",
    response_model=PageOut[EntitlementTenantRowOut],
    dependencies=[_VIEW_ENTITLEMENTS],
)
def list_object_tenants(
    object_type: str,
    object_id: UUID,
    service: EntitlementServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PageOut[EntitlementTenantRowOut]:
    """对象反查持有权益的租户（资源运营视角，必须分页）。"""
    result = service.list_tenants_by_object(object_type, object_id, page=page, page_size=page_size)
    return PageOut[EntitlementTenantRowOut](
        items=[EntitlementTenantRowOut.model_validate(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/preview",
    response_model=EntitlementPreviewOut,
    dependencies=[_VIEW_ENTITLEMENTS],
)
def preview_batch(
    payload: EntitlementBatchRequest,
    service: EntitlementServiceDep,
) -> EntitlementPreviewOut:
    """dry-run：不改库，返回将新增/将失效（含角色授权影响面）/无变化三组。"""
    preview = service.preview(
        payload.tenant_id,
        payload.mode,
        [EntitlementItem(item.object_type, item.object_id) for item in payload.items],
    )
    return EntitlementPreviewOut.model_validate(preview)


@router.post(
    "/batch",
    response_model=EntitlementBatchOut,
    dependencies=[_MANAGE_ENTITLEMENTS],
)
async def apply_batch(
    payload: EntitlementBatchRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EntitlementServiceDep,
) -> EntitlementBatchOut:
    """批量开通/软失效：单事务不做部分成功；revoke 返回影响的角色授权数。"""
    ip, user_agent = client_meta(request)
    result = await service.apply_batch(
        payload.tenant_id,
        payload.mode,
        [EntitlementItem(item.object_type, item.object_id) for item in payload.items],
        reason=payload.reason,
        auth_type=payload.auth_type,
        start_time=payload.start_time,
        expire_time=payload.expire_time,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EntitlementBatchOut(
        updated=result.updated,
        failed=list(result.failed),
        affected_role_grants=result.affected_role_grants,
    )


@router.post(
    "/purge",
    response_model=EntitlementPurgeOut,
    dependencies=[_MANAGE_ENTITLEMENTS],
)
async def purge_entitlement(
    payload: EntitlementPurgeRequest,
    principal: AdminAuthDep,
    service: EntitlementServiceDep,
) -> EntitlementPurgeOut:
    """权益清除：仅平台 superadmin + 显式二次确认；先写审计快照再物理删除并连带角色授权行。"""
    result = await service.purge(
        payload.tenant_id,
        payload.object_type,
        payload.object_id,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_code=principal.role_code,
        confirm=payload.confirm,
        reason=payload.reason,
    )
    return EntitlementPurgeOut.model_validate(result)


@router.get("/plans", response_model=PageOut[EntitlementPlanOut], dependencies=[_VIEW_ENTITLEMENTS])
def list_plans(
    service: EntitlementServiceDep,
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PageOut[EntitlementPlanOut]:
    """套餐模板分页列表（平台级定义）。"""
    result = service.list_plans(keyword=keyword, page=page, page_size=page_size)
    return PageOut[EntitlementPlanOut](
        items=[EntitlementPlanOut.model_validate(plan) for plan in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/plans/{plan_id}", response_model=EntitlementPlanOut, dependencies=[_VIEW_ENTITLEMENTS]
)
def get_plan(plan_id: UUID, service: EntitlementServiceDep) -> EntitlementPlanOut:
    """套餐模板详情（含条目集合）。"""
    return EntitlementPlanOut.model_validate(service.get_plan(plan_id))


@router.post(
    "/plans",
    response_model=EntitlementPlanOut,
    status_code=201,
    dependencies=[_MANAGE_ENTITLEMENTS],
)
def create_plan(
    payload: EntitlementPlanCreateRequest,
    principal: AdminAuthDep,
    service: EntitlementServiceDep,
) -> EntitlementPlanOut:
    """创建套餐模板：code 全局唯一，条目对象需存在；模板不落权益。"""
    plan_id = service.create_plan(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        auth_type=payload.auth_type,
        duration_days=payload.duration_days,
        quota=payload.quota,
        items=[EntitlementItem(item.object_type, item.object_id) for item in payload.items],
        actor_id=principal.user_id,
        actor_username=principal.username,
    )
    return EntitlementPlanOut.model_validate(service.get_plan(plan_id))


@router.delete("/plans/{plan_id}", dependencies=[_MANAGE_ENTITLEMENTS])
def delete_plan(
    plan_id: UUID,
    principal: AdminAuthDep,
    service: EntitlementServiceDep,
) -> dict[str, bool]:
    """删除套餐定义（条目级联清除）；已开通的权益不受影响。"""
    service.delete_plan(plan_id, actor_id=principal.user_id, actor_username=principal.username)
    return {"ok": True}


@router.post(
    "/plans/{plan_id}/apply",
    response_model=EntitlementBatchOut,
    dependencies=[_MANAGE_ENTITLEMENTS],
)
async def apply_plan(
    plan_id: UUID,
    payload: EntitlementPlanApplyRequest,
    principal: AdminAuthDep,
    request: Request,
    service: EntitlementServiceDep,
) -> EntitlementBatchOut:
    """套餐开通：展开条目套用模板默认 auth_type/期限，复用批量单事务语义（失败整体不落库）。"""
    ip, user_agent = client_meta(request)
    result = await service.apply_plan(
        payload.tenant_id,
        plan_id,
        start_time=payload.start_time,
        expire_time=payload.expire_time,
        reason=payload.reason,
        actor_id=principal.user_id,
        actor_username=principal.username,
        ip=ip,
        user_agent=user_agent,
    )
    return EntitlementBatchOut(
        updated=result.updated,
        failed=list(result.failed),
        affected_role_grants=result.affected_role_grants,
    )


@router.post(
    "/applications/{application_id}/grant",
    response_model=GrantApplicationOut,
    dependencies=[_MANAGE_ENTITLEMENTS],
)
async def grant_application(
    application_id: UUID,
    payload: GrantApplicationPayload,
    principal: AdminAuthDep,
    uow: UowDep,
    service: GrantEngineServiceDep,
) -> GrantApplicationOut:
    """OPS 直开应用：active/wait_effect 判定、审计与缓存失效全部收口在 GrantService.create_grant。"""
    try:
        instance_id = await service.create_grant(
            CreateGrantRequest(
                tenant_id=payload.tenant_id,
                app_id=application_id,
                auth_type=payload.auth_type,
                contract_no=payload.contract_no,
                quota_json=payload.quota_json,
                start_time=payload.start_time,
                expire_time=payload.expire_time,
                remark=payload.remark,
                operator_id=principal.user_id,
                operator_name=principal.username,
            )
        )
    except GrantError as exc:
        # 重复开通等引擎约束按既有约定转 422（409 映射留待全局异常处理器统一补）
        raise ValidationError(str(exc)) from exc
    uow.commit()
    return GrantApplicationOut(instance_id=instance_id)
