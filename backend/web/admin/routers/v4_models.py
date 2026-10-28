"""v4 模型目录管理接口：provider + model_catalog CRUD。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from internal.application.v4.model_service import V4ModelService
from web.deps.auth import require_platform_admin
from web.deps.db import UowDep

# 模型目录是平台级配置（provider / api_key / base_url），仅平台管理员可读写
router = APIRouter(
    prefix="/v4/models",
    tags=["v4-models"],
    dependencies=[Depends(require_platform_admin)],
)


def get_model_service(uow: UowDep) -> V4ModelService:
    return V4ModelService(uow.session)


ModelServiceDep = Depends(get_model_service)


# ========== schemas ==========
class ProviderCreatePayload(BaseModel):
    name: str = Field(..., max_length=100)
    base_url: str = Field(..., max_length=500)
    api_key: str = Field(..., max_length=500)
    owner_type: str = Field(default="platform")
    owner_id: UUID | None = None


class ProviderUpdatePayload(BaseModel):
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    is_enabled: bool | None = None


class CatalogCreatePayload(BaseModel):
    provider_id: UUID
    model_id: str = Field(..., max_length=100)
    display_name: str = Field("", max_length=200)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class CatalogUpdatePayload(BaseModel):
    provider_id: UUID | None = None
    display_name: str | None = Field(None, max_length=200)
    capabilities: dict[str, Any] | None = None
    is_enabled: bool | None = None


# ========== provider ==========
@router.get("/providers")
def list_providers(service: V4ModelService = ModelServiceDep) -> list[dict]:
    """列出所有模型 provider。"""
    return service.list_providers()


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_provider(
    payload: ProviderCreatePayload,
    service: V4ModelService = ModelServiceDep,
) -> dict:
    """创建模型 provider。"""
    provider_id = service.create_provider(
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
    )
    return {"provider_id": provider_id}


@router.patch("/providers/{provider_id}")
def update_provider(
    provider_id: UUID,
    payload: ProviderUpdatePayload,
    service: V4ModelService = ModelServiceDep,
) -> dict:
    """更新 provider（base_url / api_key / is_enabled）。"""
    service.update_provider(
        provider_id,
        base_url=payload.base_url,
        api_key=payload.api_key,
        is_enabled=payload.is_enabled,
    )
    return {"ok": True}


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: UUID, service: V4ModelService = ModelServiceDep) -> None:
    """删除 provider。"""
    service.delete_provider(provider_id)


# ========== catalog ==========
@router.get("/catalog")
def list_catalog(service: V4ModelService = ModelServiceDep) -> list[dict]:
    """列出所有模型（admin 视图，含禁用项）。"""
    return service.list_catalog_full()


@router.get("/catalog/available")
def list_available(service: V4ModelService = ModelServiceDep) -> list[dict]:
    """列出已启用模型（供画布 llm 节点下拉选择）。"""
    return service.list_catalog()


@router.post("/catalog", status_code=status.HTTP_201_CREATED)
def create_catalog(
    payload: CatalogCreatePayload,
    service: V4ModelService = ModelServiceDep,
) -> dict:
    """在 provider 下注册模型。"""
    catalog_id = service.create_catalog(
        provider_id=payload.provider_id,
        model_id=payload.model_id,
        display_name=payload.display_name,
        capabilities=payload.capabilities,
    )
    return {"catalog_id": catalog_id}


@router.patch("/catalog/{catalog_id}")
def update_catalog(
    catalog_id: UUID,
    payload: CatalogUpdatePayload,
    service: V4ModelService = ModelServiceDep,
) -> dict:
    """更新模型元数据。"""
    service.update_catalog(
        catalog_id,
        provider_id=payload.provider_id,
        display_name=payload.display_name,
        capabilities=payload.capabilities,
        is_enabled=payload.is_enabled,
    )
    return {"ok": True}


@router.delete("/catalog/{catalog_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_catalog(catalog_id: UUID, service: V4ModelService = ModelServiceDep) -> None:
    """删除模型。"""
    service.delete_catalog(catalog_id)
