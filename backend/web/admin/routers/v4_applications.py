"""v4 应用市场接口：浏览产品级应用、自助开通、我的应用列表、租户运行。"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import NotFoundError, ValidationError
from internal.application.v4.application_service import V4ApplicationService
from internal.application.v4.model_service import V4ModelService
from internal.engine.v4.runner import GraphRunner
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v4/marketplace", tags=["v4-marketplace"])


class SubscribePayload(BaseModel):
    application_id: UUID


class RunPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


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


@router.post("/applications/{application_id}/run")
async def run_application(
    application_id: UUID,
    payload: RunPayload,
    service: V4ServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """租户运行已开通的应用：按 tenant_id 加载 effective_config（含 pin 字段）。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    instance = service._repo.get_instance(tenant_id, application_id)  # noqa: SLF001
    if instance is None:
        raise NotFoundError("该应用未开通或不存在")

    graph = service.build_effective_graph(application_id, tenant_id)

    model_service = V4ModelService(uow.session)
    runner = GraphRunner(
        graph=graph,
        tenant_id=tenant_id,
        application_id=application_id,
        model_resolver=lambda mid: model_service.get_client_for_tenant(mid, tenant_id),
    )
    output = await runner.invoke(payload.inputs)
    return {"output": output, "run_id": str(runner.run_id)}
