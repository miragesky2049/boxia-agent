"""平台应用管理接口：平台管理员创建/编辑/上下架应用。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from functools import partial
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.canvas_debug_service import CanvasDebugService
from internal.application.errors import ValidationError
from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.graph.runtime import GraphRuntime
from web.admin.schemas.apps import (
    AppBatchDeleteOut,
    AppBatchDeleteRequest,
    AppCopyOut,
    AppCreatePayload,
    AppDeleteOut,
    AppUpdatePayload,
    DebugConversationPayload,
    DebugNodeRunPayload,
    DebugResumePayload,
    DebugRunPayload,
    EnabledPayload,
    GraphPayload,
    ListingPayload,
    PinGraphVersionPayload,
    RollbackGraphPayload,
    TenantConfigPayload,
    UserVariablesPayload,
    ValidateGraphPayload,
    VariablesPayload,
)
from web.deps.apps_services import make_application_service, make_conversation_admin_service
from web.deps.auth import AdminAuthDep, PlatformAdminDep, require_permission, require_platform_admin
from web.deps.db import UowDep
from web.deps.graph import (
    make_canvas_debug_runtime,
    register_conversation_services,
    register_llm_and_http,
    register_subgraph_loader,
)
from web.deps.sse import SSE_HEADERS, sse_event

logger = logging.getLogger(__name__)

# 画布试运行属于临时调试上下文：用固定 debug 应用 ID 作为 conversation/message 行的 application_id，
# 这样初始 run 与 resume 续跑能读到同一份会话历史。
DEBUG_APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000001")

# 应用管理是产品级平台运营能力：租户子域名管理员无权调用
router = APIRouter(
    prefix="/apps",
    tags=["apps-admin"],
    dependencies=[Depends(require_platform_admin)],
)


def get_app_service(uow: UowDep) -> ApplicationService:
    return make_application_service(uow)


AppServiceDep = Depends(get_app_service)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:255] or None
    return ip, user_agent


@router.get("")
def list_apps(
    owner_type: str | None = None,
    marketplace_only: bool = False,
    service: ApplicationService = AppServiceDep,
) -> list[dict]:
    """平台应用列表。"""
    return service.list_applications(
        owner_type=owner_type,
        include_marketplace_only=marketplace_only,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_app(
    payload: AppCreatePayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """创建平台应用（未上架）。"""
    app_id = service.create_platform_application(
        name=payload.name,
        description=payload.description,
        flow_type=payload.flow_type,
        visibility_template=payload.visibility_template,
        visibility_lock=payload.visibility_lock,
    )
    return {"application_id": app_id}


@router.post("/validate-graph")
def validate_graph_endpoint(
    payload: ValidateGraphPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """不保存、不执行，只返回 graph 结构校验结果（error/warning 清单）。

    传 application_id 时附带变量声明作用域，未声明的 `{{variables.x}}` /
    `{{system.X}}` 会以 warning 返回，不阻断试运行。
    """
    from internal.domain.canvas.validate import validate_raw_graph

    variable_names: set[str] | None = None
    system_names: set[str] | None = None
    if payload.application_id is not None:
        variable_names, system_names = service.validation_variable_scope(
            payload.application_id
        )

    issues = validate_raw_graph(
        payload.graph,
        variable_names=variable_names,
        system_names=system_names,
    )
    return {
        "valid": not any(i.severity == "error" for i in issues),
        "issues": [
            {
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "node_id": i.node_id,
            }
            for i in issues
        ],
    }


@router.get("/{application_id}")
def get_app(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """获取应用详情。"""
    app = service._repo.get_application(application_id)  # noqa: SLF001
    if app is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("应用不存在")
    return app


@router.patch("/{application_id}")
def update_app(
    application_id: UUID,
    payload: AppUpdatePayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """更新应用基本信息。"""
    service.update_application(
        application_id,
        name=payload.name,
        description=payload.description,
        avatar_url=payload.avatar_url,
        flow_type=payload.flow_type,
        visibility_template=payload.visibility_template,
        visibility_lock=payload.visibility_lock,
        admin_scope_mode=payload.admin_scope_mode,
    )
    return {"ok": True}


@router.post("/{application_id}/copy", response_model=AppCopyOut, status_code=status.HTTP_201_CREATED)
def copy_app(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> AppCopyOut:
    """复制产品级应用：复制主行、当前 graph、最新版本、可见范围。

    副本默认未启用、未上架、未发布；名称自动加「的副本」/「的副本N」后缀。
    不复制租户开通关系、会话、运行、用量等运行态数据。
    """
    actor_id = getattr(principal, "user_id", None) if principal else None
    actor_username = getattr(principal, "username", "") if principal else ""
    result = service.copy_application(
        application_id,
        actor_id=actor_id,
        actor_username=actor_username,
    )
    return AppCopyOut.model_validate(result)


@router.post(
    "/batch",
    response_model=AppBatchDeleteOut,
    dependencies=[Depends(require_permission("button:app:delete"))],
)
def batch_delete_apps(
    payload: AppBatchDeleteRequest,
    request: Request,
    principal: AdminAuthDep,
    service: ApplicationService = AppServiceDep,
) -> AppBatchDeleteOut:
    """批量物理删除应用：逐应用独立事务，部分成功，返回每项明细。"""
    ip, user_agent = _client_meta(request)
    result = service.batch_delete_applications(
        payload.application_ids,
        confirm=payload.confirm,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_code=principal.role_code,
        ip=ip,
        user_agent=user_agent,
        reason=payload.reason,
    )
    return AppBatchDeleteOut.model_validate(result)


@router.delete(
    "/{application_id}",
    response_model=AppDeleteOut,
    dependencies=[Depends(require_permission("button:app:delete"))],
)
def delete_app(
    application_id: UUID,
    request: Request,
    principal: AdminAuthDep,
    confirm: bool = Query(..., description="二次确认位，必须为 true"),
    service: ApplicationService = AppServiceDep,
) -> AppDeleteOut:
    """物理删除应用及其全部关联数据（仅平台 superadmin，不可逆）。"""
    ip, user_agent = _client_meta(request)
    result = service.delete_application(
        application_id,
        confirm=confirm,
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_role_code=principal.role_code,
        ip=ip,
        user_agent=user_agent,
    )
    return AppDeleteOut.model_validate(result)


@router.get("/{application_id}/variables")
def get_app_variables(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """读取应用变量定义与只读系统变量。"""
    return service.get_variables(application_id)


@router.put("/{application_id}/variables")
def save_app_variables(
    application_id: UUID,
    payload: VariablesPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """保存应用变量/用户变量定义。"""
    return service.save_variables(application_id, payload.variables)


@router.get("/{application_id}/user-variables")
def get_current_user_variables(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> dict:
    """读取当前登录用户在该应用下的变量取值（缺失回退默认值）。"""
    user_id = getattr(principal, "user_id", None)
    if user_id is None:
        raise ValidationError("缺少当前用户上下文")
    return {"values": service.get_user_variables(application_id, user_id)}


@router.put("/{application_id}/user-variables")
def save_current_user_variables(
    application_id: UUID,
    payload: UserVariablesPayload,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> dict:
    """写入当前登录用户的用户变量取值（用于调试/测试数据）。"""
    user_id = getattr(principal, "user_id", None)
    if user_id is None:
        raise ValidationError("缺少当前用户上下文")
    return {"values": service.save_user_variables(application_id, user_id, payload.values)}


@router.get("/{application_id}/graph")
def get_app_graph(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """获取应用的 graph 定义。"""
    graph = service.get_graph(application_id)
    if graph is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("graph 不存在")
    return graph


@router.put("/{application_id}/graph")
def save_app_graph(
    application_id: UUID,
    payload: GraphPayload,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> dict:
    """保存 graph 定义：写整图版本快照 + 审计 + 缓存失效。"""
    actor_id = getattr(principal, "user_id", None) if principal else None
    actor_username = getattr(principal, "username", "") if principal else ""
    return service.save_graph(
        application_id,
        payload.graph,
        changelog=payload.changelog,
        actor_id=actor_id,
        actor_username=actor_username,
    )


@router.get("/{application_id}/graph-versions")
def list_graph_versions(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> list[dict]:
    """列出整图版本历史（替代旧 field-versions）。"""
    return service.list_graph_versions(application_id)


@router.post("/{application_id}/graph-rollback")
def rollback_graph(
    application_id: UUID,
    payload: RollbackGraphPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """回滚到指定历史版本：把该版本 graph 作为新版本再写一次。"""
    return service.rollback_graph(application_id, payload.version)


@router.post("/{application_id}/publish")
def publish_app_graph(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
    principal: PlatformAdminDep = None,
) -> dict:
    """发布动作：把当前 draft（latest）整图版本快照为 live。

    发布后 user chat 路由读 get_runtime_graph 时取 published_graph_version，
    而不是未发布的最新 draft；未发布时回退到 latest，保证老应用向后兼容。
    """
    actor_id = getattr(principal, "user_id", None) if principal else None
    actor_username = getattr(principal, "username", "") if principal else ""
    return service.publish_graph(
        application_id,
        actor_id=actor_id,
        actor_username=actor_username,
    )


@router.post("/{application_id}/tenant-config", status_code=status.HTTP_201_CREATED)
def set_tenant_config(
    application_id: UUID,
    payload: TenantConfigPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """设置租户级 config 覆盖（key 形如 graph.nodes.{node_id}.config.{field}）。"""
    service.set_tenant_config(
        tenant_id=payload.tenant_id,
        application_id=application_id,
        config_key=payload.config_key,
        config_value=payload.config_value,
    )
    return {"ok": True}


@router.delete("/{application_id}/tenant-config")
def delete_tenant_config(
    application_id: UUID,
    tenant_id: UUID,
    config_key: str,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """删除租户级 config 覆盖。"""
    service.delete_tenant_config(tenant_id, application_id, config_key)
    return {"ok": True}


@router.post("/{application_id}/graph-pin")
def pin_graph_version(
    application_id: UUID,
    payload: PinGraphVersionPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """租户锁定整图版本；version=None 回到 latest。"""
    service.pin_graph_version(
        tenant_id=payload.tenant_id,
        application_id=application_id,
        version=payload.version,
    )
    return {"ok": True}


@router.post("/{application_id}/listing")
def set_listing(
    application_id: UUID,
    payload: ListingPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """上架 / 下架应用到市场。"""
    service.set_listed_in_market(application_id, payload.listed)
    return {"ok": True}


@router.post("/{application_id}/enabled")
def set_enabled(
    application_id: UUID,
    payload: EnabledPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """启用 / 禁用应用。"""
    service.set_enabled(application_id, payload.enabled)
    return {"ok": True}


# 0068：老 GET/PUT /{application_id}/visibility 已下线（全局 visibility_mode 模型推翻），
# 租户侧可见范围接口见 web/admin/routers/tenant_apps.py（/admin/tenant/apps/{id}/visibility）


async def _sse_frames(
    stream: AsyncIterator[tuple[str, dict[str, Any]]],
) -> AsyncIterator[str]:
    """把应用层 (event_name, payload) 元组流格式化为 SSE 帧。"""
    async for name, data in stream:
        yield sse_event(name, data)


def _make_debug_service(uow: UowDep, principal: Any) -> CanvasDebugService:
    """组合根注入：试运行 runtime 装配闭包 uow/principal，应用层只见调试参数。"""
    return CanvasDebugService(
        runtime_factory=partial(make_canvas_debug_runtime, uow, principal),
    )


@router.post("/debug/run/stream")
async def debug_run_stream(
    payload: DebugRunPayload,
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> StreamingResponse:
    """画布 SSE 流式试运行：逐节点外抛 node_start / node_end，最后发 result。

    不依赖已保存的应用，直接用画布 graph 跑（前端编辑中实时试运行）。
    仅平台管理员可用；节点数上限保护试运行不被滥用。
    人审中断（human_approval 节点）会发 `interrupted` 事件，前端拿到 thread_id 后调 /debug/run/stream/resume 续跑。
    编排下沉 CanvasDebugService：校验/装配错误在流外（本协程内）抛出，与迁移前一致。
    """
    stream = await _make_debug_service(uow, _principal).open_run(
        graph=payload.graph,
        inputs=payload.inputs,
        application_id=payload.application_id or DEBUG_APPLICATION_ID,
        variables_application_id=payload.application_id,
        conversation_id=payload.conversation_id,
        thread_id=payload.thread_id,
    )
    return StreamingResponse(
        _sse_frames(stream),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/debug/run/node")
async def debug_run_node(
    payload: DebugNodeRunPayload,
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> dict:
    """单节点试运行：只执行指定节点并返回 outputs / 耗时 / 错误。

    不写 run 记录、不发 SSE、不改变全图试运行语义；画布未保存也可用。
    上游引用按空值求值，用户在抽屉表单里填写的入参优先。
    """
    nodes = payload.graph.get("nodes") or []
    if not isinstance(nodes, list) or not nodes or len(nodes) > 50:
        raise ValidationError("graph 节点数必须在 1-50 之间")

    services = ServiceRegistry()
    register_llm_and_http(services, uow, _principal.tenant_id)

    run_id = uuid.uuid4()
    register_conversation_services(
        services, uow,
        tenant_id=_principal.tenant_id,
        user_id=_principal.user_id,
        application_id=DEBUG_APPLICATION_ID,
        run_id=run_id,
    )
    register_subgraph_loader(services, make_application_service(uow), _principal.tenant_id)

    runtime = GraphRuntime(
        canvas_json=payload.graph,
        services=services,
        run_id=run_id,
        tenant_id=_principal.tenant_id,
        user_id=_principal.user_id,
        application_id=DEBUG_APPLICATION_ID,
        conversation_id=payload.conversation_id,
        # 单节点试运行不落 LangGraph 状态，避免依赖 checkpoint 连接
        checkpointer=None,
    )
    try:
        return await runtime.invoke_node(payload.node_id, payload.inputs)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("/debug/conversations", status_code=status.HTTP_201_CREATED)
def create_debug_conversation(
    payload: DebugConversationPayload,
    uow: UowDep,
    principal: PlatformAdminDep,
) -> dict:
    """为画布对话流试运行创建会话（channel=debug，不进入用户端会话列表）。"""
    if principal.tenant_id is None or principal.user_id is None:
        raise ValidationError("无法识别租户或用户")
    conversation_id = make_conversation_admin_service(uow).create_debug_conversation(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        application_id=payload.application_id,
        title=payload.title,
    )
    return {"conversation_id": str(conversation_id)}


@router.post("/debug/run/stream/resume")
async def debug_run_stream_resume(
    payload: DebugResumePayload,
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> StreamingResponse:
    """人审 / 问答续跑：用 thread_id + Command(resume=...) 从 interrupt 点继续。"""
    resume_value = payload.resume if payload.resume is not None else payload.approval
    if resume_value is None:
        raise ValidationError("续跑载荷不能为空")

    stream = await _make_debug_service(uow, _principal).open_resume(
        graph=payload.graph,
        resume_value=resume_value,
        run_id=uuid.UUID(payload.run_id) if payload.run_id else uuid.uuid4(),
        application_id=payload.application_id or DEBUG_APPLICATION_ID,
        variables_application_id=payload.application_id,
        conversation_id=payload.conversation_id,
        thread_id=payload.thread_id,
    )
    return StreamingResponse(
        _sse_frames(stream),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
