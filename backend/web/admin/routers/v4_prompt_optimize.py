"""v4 prompt 优化接口：平台管理员在编排器里一键优化 LLM 节点的 system_prompt。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.errors import ValidationError
from internal.application.v4.model_service import V4ModelService
from internal.application.v4.prompt_optimize_service import PromptOptimizeService
from web.deps.auth import require_platform_admin
from web.deps.db import UowDep

logger = logging.getLogger(__name__)

# 编排器场景：平台管理员使用；租户自助编排场景后续可放开
router = APIRouter(
    prefix="/v4/prompt-optimize",
    tags=["v4-prompt-optimize"],
    dependencies=[Depends(require_platform_admin)],
)


class OptimizePayload(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=100)
    current_prompt: str = Field(..., min_length=1, max_length=8000)
    task_description: str = Field("", max_length=2000)


def get_model_service(uow: UowDep) -> V4ModelService:
    return V4ModelService(uow.session)


ModelServiceDep = Annotated[V4ModelService, Depends(get_model_service)]


@router.post("")
async def optimize_prompt(
    payload: OptimizePayload,
    model_service: ModelServiceDep,
) -> dict:
    """调 LLM 优化 system prompt，返回优化结果与改动建议。不落库。"""
    if not payload.current_prompt.strip():
        raise ValidationError("current_prompt 不能为空")
    service = PromptOptimizeService(model_service)
    result = await service.optimize(
        model_id=payload.model_id,
        current_prompt=payload.current_prompt,
        task_description=payload.task_description,
    )
    return result
