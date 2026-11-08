"""应用市场接口：浏览产品级应用、自助开通、我的应用列表、租户运行（含人审 interrupt/resume）。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from internal.application.apps.application_service import ApplicationService
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.graph.runtime import GraphInterrupted, GraphRuntime
from web.deps.apps_services import (
    make_application_service,
    make_apply_service,
    make_run_service,
    make_webhook_service,
)
from web.deps.auth import AdminAuthDep
from web.deps.db import UowDep
from web.deps.graph import build_runner
from web.deps.tenant import RequestContextDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


class SubscribePayload(BaseModel):
    application_id: UUID


class RunPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class ResumePayload(BaseModel):
    approved: bool
    comment: str = ""


def get_app_service(uow: UowDep) -> ApplicationService:
    return make_application_service(uow)


AppServiceDep = Annotated[ApplicationService, Depends(get_app_service)]


@router.get("/applications")
def list_marketplace(
    service: AppServiceDep,
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    """浏览应用市场（cursor 分页）。"""
    from datetime import datetime

    cursor_dt = datetime.fromisoformat(cursor) if cursor else None
    return service.list_marketplace(cursor_updated_at=cursor_dt, limit=limit)


@router.get("/applications/{application_id}")
def get_marketplace_application(
    application_id: UUID,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """市场应用详情：基本信息 + 当前租户的授权/申请状态。

    返回字段：
    - application: 应用基本信息（name/avatar/description/sale_mode/support_trial/doc_url）
    - my_subscription: 当前租户已开通记录（无则 null）
    - my_latest_apply: 当前租户最近一条申请单（无则 null）
    - inputs: start 节点定义的输入变量（运行表单用）
    """
    app = service.get_marketplace_application(application_id)
    if app is None:
        raise NotFoundError("应用不存在或未上架市场")

    tenant_id = context.tenant_id
    my_subscription = None
    my_latest_apply = None
    if tenant_id is not None:
        my_subscription = service.get_tenant_instance(tenant_id, application_id)
        my_latest_apply = make_apply_service(uow).get_latest_apply(tenant_id, application_id)

    graph = service.build_effective_graph_sync(application_id, tenant_id)
    # coze 标准 type="1" 为 START；兼容早期简化格式 type="start"
    start_node = next(
        (n for n in graph.get("nodes", []) if n.get("type") in ("1", "start")),
        None,
    )
    inputs = (start_node or {}).get("config", {}).get("inputs") or []

    return {
        "application": app,
        "my_subscription": my_subscription,
        "my_latest_apply": my_latest_apply,
        "inputs": inputs,
    }


@router.post("/subscribe")
def subscribe(
    payload: SubscribePayload,
    service: AppServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户自助开通应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.subscribe(context.tenant_id, payload.application_id)


@router.get("/my-apps")
def list_my_apps(
    service: AppServiceDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户查看已开通的应用。"""
    if context.tenant_id is None:
        raise ValidationError("无法识别租户")
    return service.list_my_apps(context.tenant_id)


async def _build_runner(
    service: ApplicationService,
    uow: UowDep,
    context: Any,
    tenant_id: UUID,
    application_id: UUID,
    thread_id: str | None = None,
    run_id: UUID | None = None,
    current_user_id: UUID | None = None,
    actor_username: str | None = None,
) -> GraphRuntime:
    """兼容包装：转发到 web.deps.graph.build_runner。"""
    return await build_runner(
        service,
        uow,
        context,
        tenant_id=tenant_id,
        application_id=application_id,
        thread_id=thread_id,
        run_id=run_id,
        current_user_id=current_user_id,
        actor_username=actor_username,
    )


@router.post("/applications/{application_id}/run")
async def run_application(
    application_id: UUID,
    payload: RunPayload,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
) -> dict:
    """租户运行已开通的应用。

    - 正常完成：{"status": "success", "output": ...}
    - 遇到人审节点：{"status": "waiting_approval", "thread_id": "...", "approval": {...}}
    """
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    service.require_runtime_instance(tenant_id, application_id)

    runner = await _build_runner(
        service,
        uow,
        context,
        tenant_id,
        application_id,
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )
    try:
        output = await runner.invoke(payload.inputs)
        uow.commit()
        return {
            "status": "success",
            "output": output,
            "thread_id": runner.thread_id,
            "run_id": runner.run_id,
        }
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "thread_id": runner.thread_id,
            "run_id": runner.run_id,
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


@router.post("/applications/{application_id}/runs/{thread_id}/resume")
async def resume_application(
    application_id: UUID,
    thread_id: str,
    payload: ResumePayload,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
) -> dict:
    """人审节点恢复执行：提交审批结果后继续跑图。

    resume 前先查 run 表校验 ownership：thread_id 必须属于 (tenant_id, application_id)
    且状态为 interrupted，否则 404。防止跨租户通过伪造 thread_id 接管他人运行。

    同时校验人审节点配置的 assignee_role：当前 principal 的 role_code 必须匹配，
    superadmin 始终放行（超管兜底）。不匹配抛 403。
    """
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    service.require_runtime_instance(tenant_id, application_id)

    pending = make_run_service(uow).get_running_for_thread(tenant_id, application_id, thread_id)

    # 0074 PRD F10（M3）：agent 工具审批是"应用层快照挂起"，不是 langgraph 人审节点，
    # 只能由发起用户在对话端裁决；管理端 resume 通道显式拒绝，防止越权代答
    # （正常路径下 get_interrupt_state 也取不到挂起态会 403，这里给出更明确的 422）。
    pending_payload = pending.get("interrupt_payload")
    if isinstance(pending_payload, dict) and pending_payload.get("type") == "tool_approval":
        raise ValidationError("工具审批需由用户在对话端裁决，管理端不支持恢复此类中断")

    runner = await _build_runner(
        service,
        uow,
        context,
        tenant_id,
        application_id,
        thread_id=thread_id,
        run_id=pending["id"],
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )

    # 人审角色校验：从 checkpointer 取出当前 interrupt payload，比对 assignee_role
    # fail-closed：读不到 interrupt 或节点未配 assignee_role 时拒绝恢复，避免越权放行
    interrupt_state = await runner.get_interrupt_state()
    if interrupt_state is None:
        raise ForbiddenError("无法读取人审节点配置，禁止恢复执行")

    required_role = interrupt_state.get("assignee_role")
    if not required_role:
        raise ForbiddenError("人审节点未配置审批角色，禁止恢复执行")

    if principal.role_code != "superadmin" and principal.role_code != required_role:
        raise ForbiddenError(
            f"该人审节点要求角色 {required_role}，当前角色 {principal.role_code} 无权审批"
        )

    try:
        output = await runner.resume({"approved": payload.approved, "comment": payload.comment})
        uow.commit()
        return {
            "status": "success",
            "output": output,
            "thread_id": thread_id,
            "run_id": pending["id"],
        }
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "thread_id": thread_id,
            "run_id": pending["id"],
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


@router.get("/applications/{application_id}/runs")
def list_runs(
    application_id: UUID,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    limit: int = 50,
) -> list[dict]:
    """租户查看某应用的运行历史。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return make_run_service(uow).list_runs(tenant_id, workflow_id=application_id, limit=limit)


@router.get("/applications/{application_id}/inputs")
def get_application_inputs(
    application_id: UUID,
    service: AppServiceDep,
    context: RequestContextDep,
) -> dict:
    """租户查看该应用 start 节点定义的输入变量，用于动态生成运行表单。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    service.require_runtime_instance(tenant_id, application_id)

    graph = service.build_effective_graph_sync(application_id, tenant_id)
    # coze 标准 type="1" 为 START；兼容早期简化格式 type="start"
    start_node = next(
        (n for n in graph.get("nodes", []) if n.get("type") in ("1", "start")),
        None,
    )
    inputs = (start_node or {}).get("config", {}).get("inputs") or []
    return {"inputs": inputs}


@router.get("/runs/{run_id}")
def get_run_detail(
    run_id: UUID,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """查看运行详情：run 元信息 + 节点执行列表。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    return make_run_service(uow).get_run_detail(run_id, tenant_id)


@router.get("/runs/{run_id}/checkpoints")
async def list_run_checkpoints(
    run_id: UUID,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """列出某 run 的 checkpoint 历史（time-travel 用）。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    run = make_run_service(uow).get_run_owned(run_id, tenant_id)

    runner = await _build_runner(
        service,
        uow,
        context,
        tenant_id,
        run["workflow_id"],
        thread_id=run["thread_id"],
        run_id=run_id,
    )
    history = await runner.list_checkpoint_history(limit=20)
    return {"checkpoints": history}


class ForkPayload(BaseModel):
    checkpoint_id: str
    new_input: dict[str, Any] | None = None


@router.post("/runs/{run_id}/fork")
async def fork_run(
    run_id: UUID,
    payload: ForkPayload,
    service: AppServiceDep,
    uow: UowDep,
    context: RequestContextDep,
    principal: AdminAuthDep,
) -> dict:
    """从历史 checkpoint 分叉重跑：复制 state 到新 thread，从该状态继续。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")

    run_service = make_run_service(uow)
    run = run_service.get_run_owned(run_id, tenant_id)

    # 新 run_id，新 thread 由 runner 内部生成
    new_run_id = uuid.uuid4()
    runner = await _build_runner(
        service,
        uow,
        context,
        tenant_id,
        run["workflow_id"],
        run_id=new_run_id,
        current_user_id=principal.user_id,
        actor_username=principal.username,
    )

    # 先落一条新 run 记录（fork 用的 graph 直接复用 runner 加载的 graph）
    graph = (
        runner.graph_snapshot
        if hasattr(runner, "graph_snapshot")
        else service.build_effective_graph_sync(run["workflow_id"], tenant_id)
    )
    run_service.insert_run(
        run_id=new_run_id,
        tenant_id=tenant_id,
        workflow_id=run["workflow_id"],
        graph_snapshot=graph,
        input_data=payload.new_input or run["input"],
        thread_id=runner.thread_id,
    )

    try:
        result = await runner.fork_from_checkpoint(
            source_thread_id=run["thread_id"],
            checkpoint_id=payload.checkpoint_id,
            new_input=payload.new_input,
        )
        uow.commit()
        return {
            "status": "success",
            "new_run_id": str(new_run_id),
            "new_thread_id": result["new_thread_id"],
            "output": result["output"],
        }
    except GraphInterrupted as exc:
        uow.commit()
        return {
            "status": "waiting_approval",
            "new_run_id": str(new_run_id),
            "new_thread_id": runner.thread_id,
            "approval": exc.interrupt_payload,
        }
    except Exception:
        uow.commit()
        raise


# ========== webhook 通知订阅 CRUD ==========
class WebhookPayload(BaseModel):
    event_type: str = Field(..., description="run_finished / run_error / node_error")
    url: str = Field(..., description="回调 URL")
    application_id: UUID | None = Field(default=None, description="空 = 该租户所有应用")


@router.get("/webhooks")
def list_webhooks(
    uow: UowDep,
    context: RequestContextDep,
) -> list[dict]:
    """租户列出自己的 webhook 订阅。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    return make_webhook_service(uow).list_by_tenant(tenant_id)


@router.post("/webhooks")
def create_webhook(
    payload: WebhookPayload,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """创建 webhook 订阅（SSRF 校验与提交收口在 WebhookService.create）。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    wid = make_webhook_service(uow).create(
        tenant_id=tenant_id,
        event_type=payload.event_type,
        url=payload.url,
        application_id=payload.application_id,
    )
    return {"id": str(wid)}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: UUID,
    uow: UowDep,
    context: RequestContextDep,
) -> dict:
    """删除 webhook 订阅。"""
    tenant_id = context.tenant_id
    if tenant_id is None:
        raise ValidationError("无法识别租户")
    make_webhook_service(uow).delete(webhook_id, tenant_id)
    return {"ok": True}
