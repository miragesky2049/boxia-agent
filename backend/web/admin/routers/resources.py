"""统一资源接口：平台管理员管 resource + grant；租户浏览可用资源。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from internal.application.errors import ValidationError
from internal.application.apps.resource_service import AppResourceService
from web.deps.apps_services import make_app_resource_service
from web.deps.auth import PlatformAdminDep, require_platform_admin
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep

# 平台管理员路由：管理资源 + 授权给租户
admin_router = APIRouter(
    prefix="/resources",
    tags=["resource-admin"],
    dependencies=[Depends(require_platform_admin)],
)

# 租户路由：浏览可用资源
tenant_router = APIRouter(prefix="/my-resources", tags=["resource-tenant"])


def get_resource_service(uow: UowDep) -> AppResourceService:
    return make_app_resource_service(uow.session)


ResourceServiceDep = Depends(get_resource_service)


class ResourceCreatePayload(BaseModel):
    type: str = Field(..., description="tool / prompt / skill / knowledge")
    name: str = Field(..., max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    owner_type: str = Field("platform")
    owner_id: UUID | None = None


class ResourceUpdatePayload(BaseModel):
    name: str | None = Field(None, max_length=200)
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_deprecated: bool | None = None


class GrantPayload(BaseModel):
    tenant_id: UUID


# ========== admin：资源 CRUD ==========
@admin_router.get("")
def list_resources(
    type: str | None = None,
    owner_type: str | None = None,
    service: AppResourceService = ResourceServiceDep,
) -> list[dict]:
    """平台管理员列出全部资源（含禁用）。"""
    return service.list_resources(type=type, owner_type=owner_type)


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceCreatePayload,
    uow: UowDep,
    service: AppResourceService = ResourceServiceDep,
) -> dict:
    """创建资源。"""
    resource_id = service.create_resource(
        type=payload.type,
        name=payload.name,
        config=payload.config,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
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


# ========== 租户：浏览可用资源 ==========
@tenant_router.get("")
def list_my_resources(
    type: str | None = None,
    service: AppResourceService = ResourceServiceDep,
    context: RequestContextDep = None,
) -> list[dict]:
    """租户浏览可用资源：平台已 grant 的 + 自建私有资源。"""
    if context is None or context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_available(context.tenant_id, type=type)
