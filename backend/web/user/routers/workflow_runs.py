"""用户端工作流运行接口：同步调用，返回 outputs 与节点状态。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from internal.application.workflow_run_service import WorkflowRunService
from web.deps.auth import UserAuthDep
from web.deps.services import WorkflowRunServiceDep
from web.user.schemas.workflow_run import (
    WorkflowNodeStateOut,
    WorkflowRunRequest,
    WorkflowRunResponse,
)

router = APIRouter(prefix="/workflows", tags=["user-workflow-run"])


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: UUID,
    body: WorkflowRunRequest,
    service: WorkflowRunServiceDep,
    principal: UserAuthDep,
) -> WorkflowRunResponse:
    """运行一次工作流：DAG 分层调度，返回最终 outputs。"""
    result = await service.run(
        workflow_id=workflow_id,
        inputs=body.inputs,
        user_id=principal.user_id,
    )
    return WorkflowRunResponse(
        workflow_id=workflow_id,
        run_id=result.run_id,
        outputs=result.outputs,
        node_states=[
            WorkflowNodeStateOut(
                node_id=state.node_id,
                type=state.type,
                status=state.status,
                duration_ms=state.duration_ms,
                output=state.output,
                error=state.error,
            )
            for state in result.node_states
        ],
        usage=result.usage,
        finish_reason=result.finish_reason,
    )
