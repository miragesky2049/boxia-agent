"""统一资源接口：平台管理员管 resource + grant + 审核；租户浏览与自助创建资源。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from internal.application.apps.resource_service import AppResourceService
from internal.application.errors import ValidationError
from internal.domain.entity.resource import REVIEW_STATUS_PENDING
from web.deps.apps_services import make_app_resource_service
from web.deps.auth import AdminAuthDep, require_permission, require_platform_admin
from web.deps.db import UowDep
from web.deps.http import client_meta
from web.deps.tenant import RequestContextDep

# 平台管理员路由：管理资源 + 授权给租户 + 审核
admin_router = APIRouter(
    prefix="/resources",
    tags=["resource-admin"],
    dependencies=[Depends(require_platform_admin)],
)

# 租户路由：浏览与自助创建资源（创建进入 pending 走平台审核）
tenant_router = APIRouter(prefix="/my-resources", tags=["resource-tenant"])

_REVIEW_RESOURCE = Depends(require_permission("button:resource:review"))
_CREATE_TENANT_RESOURCE = Depends(require_permission("button:resource:create"))


def get_resource_service(uow: UowDep) -> AppResourceService:
    return make_app_resource_service(uow)


ResourceServiceDep = Depends(get_resource_service)


class ResourceCreatePayload(BaseModel):
    type: str = Field(..., description="tool / prompt / skill / knowledge")
    name: str = Field(..., max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    owner_type: str = Field("platform")
    owner_id: UUID | None = None


class TenantResourceCreatePayload(BaseModel):
    """租户自助创建：归属由服务端强制为本租户，不接收 owner 字段。"""

    type: str = Field(..., description="tool / prompt / skill / knowledge")
    name: str = Field(..., max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class ResourceUpdatePayload(BaseModel):
    name: str | None = Field(None, max_length=200)
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_deprecated: bool | None = None


class GrantPayload(BaseModel):
    tenant_id: UUID


class ReviewPayload(BaseModel):
    decision: Literal["approve", "reject"]
    remark: str = ""


# ========== admin：资源 CRUD ==========
@admin_router.get("")
def list_resources(
    type: str | None = None,
    owner_type: str | None = None,
    review_status: str | None = None,
    service: AppResourceService = ResourceServiceDep,
) -> list[dict]:
    """平台管理员列出全部资源（含禁用），review_status 支持审核队列过滤。"""
    return service.list_resources(type=type, owner_type=owner_type, review_status=review_status)


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceCreatePayload,
    principal: AdminAuthDep,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    """创建资源：平台级直接过审，租户归属资源进入待审。"""
    resource_id = service.create_resource(
        type=payload.type,
        name=payload.name,
        config=payload.config,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        created_by=principal.user_id,
    )
    uow.commit()
    return {"resource_id": resource_id}


@admin_router.get("/{resource_id}")
def get_resource(
    resource_id: UUID,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    return service.get_resource(resource_id)


@admin_router.patch("/{resource_id}")
def update_resource(
    resource_id: UUID,
    payload: ResourceUpdatePayload,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    service.update_resource(
        resource_id,
        name=payload.name,
        config=payload.config,
        is_enabled=payload.is_enabled,
        is_deprecated=payload.is_deprecated,
    )
    uow.commit()
    return {"ok": True}


@admin_router.delete("/{resource_id}")
def delete_resource(
    resource_id: UUID,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    service.delete_resource(resource_id)
    uow.commit()
    return {"ok": True}


# ========== admin：审核 ==========
@admin_router.post("/{resource_id}/review", dependencies=[_REVIEW_RESOURCE])
def review_resource(
    resource_id: UUID,
    payload: ReviewPayload,
    principal: AdminAuthDep,
    request: Request,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    """资源审核：通过/驳回；创建人自审按职责分离拒绝（SELF_REVIEW_FORBIDDEN）。"""
    ip, user_agent = client_meta(request)
    result = service.review_resource(
        resource_id,
        decision=payload.decision,
        reviewer_id=principal.user_id,
        reviewer_username=principal.username,
        remark=payload.remark,
        ip=ip,
        user_agent=user_agent,
    )
    uow.commit()
    return result


# ========== admin：grant ==========
@admin_router.post("/{resource_id}/grants", status_code=status.HTTP_201_CREATED)
def grant_resource(
    resource_id: UUID,
    payload: GrantPayload,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    """把平台资源开放给指定租户。"""
    service.grant_resource(resource_id, payload.tenant_id)
    uow.commit()
    return {"ok": True}


@admin_router.get("/{resource_id}/grants")
def list_grants(
    resource_id: UUID,
    service: AppResourceService = ResourceServiceDep,
) -> list[dict]:
    return service.list_grants(resource_id)


@admin_router.delete("/{resource_id}/grants/{tenant_id}")
def revoke_grant(
    resource_id: UUID,
    tenant_id: UUID,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    service.revoke_resource(resource_id, tenant_id)
    uow.commit()
    return {"ok": True}


# ========== 租户：浏览与自助创建资源 ==========
@tenant_router.get("")
def list_my_resources(
    context: RequestContextDep,
    type: str | None = None,
    service: AppResourceService = ResourceServiceDep,
) -> list[dict]:
    """租户浏览可用资源：平台已 grant 的 + 自建私有资源（含 review_status/review_remark）。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_available(context.tenant_id, type=type)


@tenant_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[_CREATE_TENANT_RESOURCE])
def create_my_resource(
    payload: TenantResourceCreatePayload,
    principal: AdminAuthDep,
    context: RequestContextDep,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    """租户自助创建资源：归属强制本租户，默认 pending 待平台审核（P1-9）。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    resource_id = service.create_resource(
        type=payload.type,
        name=payload.name,
        config=payload.config,
        owner_type="tenant",
        owner_id=context.tenant_id,
        created_by=principal.user_id,
        review_status=REVIEW_STATUS_PENDING,
    )
    uow.commit()
    return {"resource_id": resource_id, "review_status": REVIEW_STATUS_PENDING}
