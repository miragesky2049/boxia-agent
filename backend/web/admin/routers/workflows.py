"""工作流与模板管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from internal.application.workflow_service import WorkflowService
from internal.domain.entity.common import Page
from internal.domain.entity.workflow import Workflow, WorkflowTemplate
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
from web.deps.services import WorkflowServiceDep

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
