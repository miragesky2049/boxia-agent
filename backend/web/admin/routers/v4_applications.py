"""v4 应用市场接口：浏览产品级应用、自助开通、我的应用列表。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from internal.application.errors import ValidationError
from internal.application.v4.application_service import V4ApplicationService
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep

router = APIRouter(prefix="/v4/marketplace", tags=["v4-marketplace"])


class SubscribePayload(BaseModel):
    application_id: UUID


def get_v4_service(uow: UowDep) -> V4ApplicationService:
    return V4ApplicationService(uow.session)


V4ServiceDep = Annotated[V4ApplicationService, Depends(get_v4_service)]


@router.get("/applications")
def list_marketplace(service: V4ServiceDep) -> list[dict]:
    """浏览应用市场。"""
    return service.list_marketplace()


@router.post("/subscribe")
def subscribe(
    payload: SubscribePayload,
    service: V4ServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户自助开通应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.subscribe(context.tenant_id, payload.application_id)


@router.get("/my-apps")
def list_my_apps(
    service: V4ServiceDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户查看已开通的应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_my_apps(context.tenant_id)
