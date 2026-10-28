"""工作流与模板管理接口。"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.errors import AppError
from internal.application.workflow_service import WorkflowService
from internal.domain.entity.common import Page
from internal.domain.entity.workflow import Workflow, WorkflowTemplate
from internal.engine.workflow.executor import WorkflowExecutor, WorkflowRunResult
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from web.admin.schemas.common import PageOut
from web.admin.schemas.workflow import (
    GraphValidateOut,
    WorkflowClonePayload,
    WorkflowOut,
    WorkflowPayload,
    WorkflowSummaryOut,
    WorkflowTemplateOut,
    WorkflowTemplatePayload,
)
from web.deps.auth import AdminAuthDep
from web.deps.db import UowDep
from web.deps.sse import SSE_HEADERS, sse_event
from web.deps.services import WorkflowServiceDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["admin-workflows"])


def _to_workflow_page_out(
    result: Page[Workflow],
) -> PageOut[WorkflowSummaryOut]:
    return PageOut[WorkflowSummaryOut](
        items=[WorkflowSummaryOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("", response_model=PageOut[WorkflowSummaryOut])
def list_workflows(
    service: WorkflowServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
) -> PageOut[WorkflowSummaryOut]:
    """分页查询工作流（租户自有 + 产品级）。"""
    return _to_workflow_page_out(
        service.list(page, page_size, keyword, is_enabled)
    )


@router.post(
    "",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow(
    payload: WorkflowPayload,
    principal: AdminAuthDep,
    service: WorkflowServiceDep,
) -> WorkflowOut:
    """创建工作流。"""
    workflow = service.create(
        payload.model_dump(),
        actor_user_id=principal.user_id,
    )
    return WorkflowOut.model_validate(workflow)


@router.get("/templates", response_model=PageOut[WorkflowTemplateOut])
def list_templates(
    service: WorkflowServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=32),
) -> PageOut[WorkflowTemplateOut]:
    """分页查询模板市场（租户视角仅返回启用模板）。"""
    result = service.list_templates(page, page_size, keyword, category)
    return PageOut[WorkflowTemplateOut](
        items=[WorkflowTemplateOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/templates",
    response_model=WorkflowTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    payload: WorkflowTemplatePayload,
    service: WorkflowServiceDep,
) -> WorkflowTemplateOut:
    """创建模板（仅产品级）。"""
    return WorkflowTemplateOut.model_validate(
        service.create_template(payload.model_dump())
    )


@router.get("/templates/{template_id}", response_model=WorkflowTemplateOut)
def get_template(
    template_id: UUID, service: WorkflowServiceDep
) -> WorkflowTemplateOut:
    """查询模板详情。"""
    return WorkflowTemplateOut.model_validate(service.get_template(template_id))


@router.put("/templates/{template_id}", response_model=WorkflowTemplateOut)
def update_template(
    template_id: UUID,
    payload: WorkflowTemplatePayload,
    service: WorkflowServiceDep,
) -> WorkflowTemplateOut:
    """更新模板（仅产品级）。"""
    return WorkflowTemplateOut.model_validate(
        service.update_template(template_id, payload.model_dump())
    )


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_template(template_id: UUID, service: WorkflowServiceDep) -> None:
    """删除模板（仅产品级）。"""
    service.delete_template(template_id)


@router.post("/validate", response_model=GraphValidateOut)
def validate_graph(
    payload: WorkflowPayload,
    service: WorkflowServiceDep,
) -> GraphValidateOut:
    """图拓扑校验（不落库）。"""
    return GraphValidateOut.model_validate(service.validate_graph(payload.graph))


@router.post(
    "/clone-from-template/{template_id}",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
)
def clone_from_template(
    template_id: UUID,
    payload: WorkflowClonePayload,
    principal: AdminAuthDep,
    service: WorkflowServiceDep,
) -> WorkflowOut:
    """把模板复制为当前租户自有的工作流。"""
    workflow = service.clone_from_template(
        template_id,
        name=payload.name,
        description=payload.description,
        actor_user_id=principal.user_id,
    )
    return WorkflowOut.model_validate(workflow)


# ---------- 画布试运行（必须放在 /{workflow_id} 之前，避免被路径参数吞掉）----------


class WorkflowDebugRequest(BaseModel):
    """画布试运行请求：可以直接传草稿 graph，不落库。"""

    graph: dict[str, Any] = Field(..., description="要试运行的图 DSL")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Start 节点入参")


class WorkflowDebugNodeState(BaseModel):
    node_id: str
    type: str
    status: str
    duration_ms: int = 0
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkflowDebugResult(BaseModel):
    run_id: str
    outputs: dict[str, Any]
    node_states: list[WorkflowDebugNodeState]
    usage: dict[str, int]
    finish_reason: str


def _build_debug_llm_factory():
    """画布试运行用的 LLM 工厂：复用 settings，与用户端一致。"""
    from internal.engine.llm import OpenAICompatLLMClient

    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value()
    base_url = settings.llm_base_url
    timeout = settings.llm_timeout_seconds
    default_model = settings.llm_model_id

    def _factory(node_data: dict[str, Any]):
        model = str(node_data.get("model_id") or default_model)
        return OpenAICompatLLMClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
            default_temperature=float(node_data.get("temperature") or settings.llm_temperature),
            default_max_tokens=int(node_data.get("max_tokens") or settings.llm_max_tokens),
        )

    return _factory


def _to_debug_result(result: WorkflowRunResult) -> WorkflowDebugResult:
    return WorkflowDebugResult(
        run_id=result.run_id,
        outputs=result.outputs,
        node_states=[
            WorkflowDebugNodeState(
                node_id=s.node_id,
                type=s.type,
                status=s.status,
                duration_ms=s.duration_ms,
                output=s.output,
                error=s.error,
            )
            for s in result.node_states
        ],
        usage=result.usage,
        finish_reason=result.finish_reason,
    )


@router.post(
    "/debug/run",
    response_model=WorkflowDebugResult,
)
async def debug_run_workflow(
    payload: WorkflowDebugRequest,
    principal: AdminAuthDep,
    uow: UowDep,
) -> WorkflowDebugResult:
    """画布同步试运行：直接执行草稿 graph，不落库。"""
    from internal.domain.constants import PLATFORM_TENANT_ID
    from uuid import uuid4

    executor = WorkflowExecutor(llm_factory=_build_debug_llm_factory())
    synthetic_id = uuid4()
    result = await executor.run(
        workflow_id=synthetic_id,
        tenant_id=principal.tenant_id or PLATFORM_TENANT_ID,
        user_id=principal.user_id,
        graph=payload.graph,
        global_inputs=dict(payload.inputs or {}),
        uow=uow,
    )
    return _to_debug_result(result)


@router.post("/debug/run/stream")
async def debug_run_workflow_stream(
    payload: WorkflowDebugRequest,
    principal: AdminAuthDep,
    uow: UowDep,
) -> StreamingResponse:
    """画布 SSE 流式试运行：逐节点外抛 node_start / node_end，最后发 result。"""
    from internal.domain.constants import PLATFORM_TENANT_ID
    from uuid import uuid4

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def event_callback(event: str, data: dict[str, Any]) -> None:
        await queue.put(sse_event(event, data))

    executor = WorkflowExecutor(
        llm_factory=_build_debug_llm_factory(),
        event_callback=event_callback,
    )
    synthetic_id = uuid4()

    async def runner() -> None:
        try:
            result = await executor.run(
                workflow_id=synthetic_id,
                tenant_id=principal.tenant_id or PLATFORM_TENANT_ID,
                user_id=principal.user_id,
                graph=payload.graph,
                global_inputs=dict(payload.inputs or {}),
                uow=uow,
            )
            await queue.put(
                sse_event("result", _to_debug_result(result).model_dump(mode="json"))
            )
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("workflow debug stream failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())

    async def event_stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{workflow_id}", response_model=WorkflowOut)
def get_workflow(
    workflow_id: UUID, service: WorkflowServiceDep
) -> WorkflowOut:
    """查询工作流详情。"""
    return WorkflowOut.model_validate(service.get(workflow_id))


@router.put("/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowPayload,
    service: WorkflowServiceDep,
) -> WorkflowOut:
    """更新工作流（仅本租户自有）。"""
    return WorkflowOut.model_validate(
        service.update(workflow_id, payload.model_dump())
    )


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow(workflow_id: UUID, service: WorkflowServiceDep) -> None:
    """删除工作流（仅本租户自有）。"""
    service.delete(workflow_id)
