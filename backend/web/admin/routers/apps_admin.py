"""平台应用管理接口：平台管理员创建/编辑/上下架应用。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.errors import AppError, ValidationError
from internal.domain.agent.tool_executor import ToolExecutorService
from internal.domain.graph.http_service import HttpService
from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.graph.runtime import GraphInterrupted, GraphRuntime
from internal.domain.llm.adapter import LLMServiceAdapter, build_model_resolver
from internal.domain.retrieval.services import register_retrieval_services
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.async_conversation_adapter import (
    AsyncConversationRepository,
    AsyncMessageRepository,
)
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository as SyncConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import (
    MessageRepository as SyncMessageRepository,
)
from internal.infrastructure.sandbox.python_sandbox import PythonSandbox
from web.deps.auth import PlatformAdminDep, require_platform_admin
from web.deps.db import UowDep
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
    return ApplicationService(uow)


AppServiceDep = Depends(get_app_service)


def _register_conversation_services(
    services: ServiceRegistry,
    uow: UowDep,
    principal: PlatformAdminDep,
    application_id: UUID,
    run_id: UUID,
    enforce_application: bool = False,
) -> None:
    """把会话/消息仓储注册进 ServiceRegistry，供 conversation 类节点使用。

    画布试运行没有真实应用 ID（application_id 固定为 DEBUG_APPLICATION_ID），
    默认不校验应用维度，只按租户 + 用户收口，避免消息节点写入真实应用会话时报"不属于当前应用"。
    """
    tenant_id = principal.tenant_id or UUID("00000000-0000-0000-0000-000000000000")
    conv_repo = AsyncConversationRepository(
        SyncConversationRepository(uow.session),
        tenant_id=tenant_id,
        user_id=principal.user_id,
        application_id=application_id,
        enforce_application=enforce_application,
        channel="debug",
    )
    # 试运行不写 run 表，消息的 run_id 必须留空，否则触发 run 外键约束
    msg_repo = AsyncMessageRepository(
        SyncMessageRepository(uow.session),
        tenant_id=tenant_id,
        user_id=principal.user_id,
        application_id=application_id,
        run_id=None,
        enforce_application=enforce_application,
    )
    services.register("conversation_repo", conv_repo)
    services.register("message_repo", msg_repo)
    services.register(
        "tool_executor",
        ToolExecutorService(
            uow.session,
            tenant_id=tenant_id,
            user_id=principal.user_id,
            application_id=application_id,
            run_id=run_id,
        ),
    )
    register_retrieval_services(services)
    services.register("sandbox", PythonSandbox())


def _load_debug_variables(
    uow: Any,
    application_id: UUID | None,
    principal: Any,
) -> tuple[dict[str, Any], set[str], Any]:
    """画布试运行使用真实应用的变量定义；未指定应用时返回空池。"""
    if application_id is None or principal.user_id is None:
        return {}, set(), None
    try:
        variables, user_keys = ApplicationService(uow).build_runtime_variables(
            application_id, principal.user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("加载画布试运行变量失败 application=%s", application_id)
        return {}, set(), None
    repo = ApplicationRepository(uow.session)

    def _persist(values: dict[str, Any]) -> None:
        repo.set_user_variables(application_id, principal.user_id, values)

    return variables, user_keys, _persist


def _register_subgraph_loader(
    services: ServiceRegistry,
    uow: UowDep,
    tenant_id: UUID,
) -> None:
    """把 subgraph_loader 注册进 ServiceRegistry，供 Subworkflow（type=9）节点调用。

    debug 路由直接运行画布 JSON（未保存），但 Subworkflow 节点通过 workflowId
    引用其他已保存的应用图——必须能按 tenant_id 加载其 runtime graph。
    """
    app_service = ApplicationService(uow)

    async def _loader(child_app_id: str) -> dict:
        try:
            child_uuid = UUID(child_app_id)
        except ValueError:
            return {}
        try:
            return await app_service.get_runtime_graph(child_uuid, tenant_id)
        except Exception:  # noqa: BLE001
            logger.exception("debug 路由加载子图失败: child_app_id=%s", child_app_id)
            return {}

    services.register("subgraph_loader", _loader)


class AppCreatePayload(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=2000)
    # workflow（工作流） / chatflow（对话流）
    flow_type: str = Field("workflow", pattern="^(workflow|chatflow)$")


class AppUpdatePayload(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=500)
    flow_type: str | None = Field(None, pattern="^(workflow|chatflow)$")


class GraphPayload(BaseModel):
    graph: dict[str, Any]
    changelog: str = ""


class ListingPayload(BaseModel):
    listed: bool


class EnabledPayload(BaseModel):
    enabled: bool


class VisibilityDepartmentItem(BaseModel):
    department_id: UUID
    include_subtree: bool = True


class VisibilityPayload(BaseModel):
    mode: str = Field(..., pattern="^(all|custom)$")
    departments: list[VisibilityDepartmentItem] = Field(default_factory=list)
    users: list[UUID] = Field(default_factory=list)


class DebugRunPayload(BaseModel):
    graph: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    # 对话流会话上下文：消息类节点回退使用；不传则由「创建会话」节点产出
    conversation_id: UUID | None = None
    # 多轮试运行时复用同一个 thread，保证 checkpoint / 历史消息连续
    thread_id: str | None = None
    # 真实应用 ID：对话流试运行会把消息落到该应用下（channel=debug）
    application_id: UUID | None = None


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
    )
    return {"application_id": app_id}


class ValidateGraphPayload(BaseModel):
    """试运行前的结构校验请求体。"""

    graph: dict[str, Any]
    application_id: UUID | None = None


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
    )
    return {"ok": True}


class VariablesPayload(BaseModel):
    variables: list[dict[str, Any]] = Field(default_factory=list)


class UserVariablesPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


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


class RollbackGraphPayload(BaseModel):
    version: int


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


class TenantConfigPayload(BaseModel):
    tenant_id: UUID
    config_key: str
    config_value: Any


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


class PinGraphVersionPayload(BaseModel):
    tenant_id: UUID
    version: int | None = None


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


@router.get("/{application_id}/visibility")
def get_app_visibility(
    application_id: UUID,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """读取应用可见范围设置。"""
    return service.get_visibility(application_id)


@router.put("/{application_id}/visibility")
def replace_app_visibility(
    application_id: UUID,
    payload: VisibilityPayload,
    service: ApplicationService = AppServiceDep,
) -> dict:
    """整体覆盖应用可见范围：mode=all 全员可见；mode=custom 按部门/用户白名单收敛。"""
    return service.replace_visibility(
        application_id,
        mode=payload.mode,
        departments=[d.model_dump() for d in payload.departments],
        users=list(payload.users),
    )


async def _push_interrupt(
    queue: asyncio.Queue[str | None],
    exc: GraphInterrupted,
    runtime: GraphRuntime,
) -> None:
    """把中断翻译成 SSE：问答节点发 question，人审节点发 interrupted。"""
    payload = exc.interrupt_payload or {}
    common = {
        "thread_id": exc.thread_id,
        "run_id": str(runtime.run_id),
        "conversation_id": str(runtime.conversation_id) if runtime.conversation_id else None,
    }
    if payload.get("type") == "question":
        await queue.put(sse_event("question", {
            **common,
            "node_id": payload.get("node_id"),
            "node_title": payload.get("node_title"),
            "question": payload.get("question") or "",
            "options": payload.get("options") or [],
        }))
    else:
        await queue.put(sse_event("interrupted", {**common, "approval": payload}))


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
    """
    nodes = payload.graph.get("nodes") or []
    if not isinstance(nodes, list) or len(nodes) > 50:
        raise ValidationError("graph 节点数必须在 1-50 之间")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    model_service = ModelService(uow.session)
    services = ServiceRegistry()
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, _principal.tenant_id)),
    )
    services.register("http", HttpService())

    run_id = uuid.uuid4()
    debug_app_id = payload.application_id or DEBUG_APPLICATION_ID
    _register_conversation_services(
        services, uow, _principal,
        application_id=debug_app_id, run_id=run_id,
    )
    _register_subgraph_loader(services, uow, _principal.tenant_id)

    async def _push_node_event(etype: str, evt_payload: dict) -> None:
        await queue.put(sse_event(etype, evt_payload))

    debug_variables, debug_user_keys, debug_persist = _load_debug_variables(
        uow, payload.application_id, _principal,
    )
    runtime = GraphRuntime(
        canvas_json=payload.graph,
        services=services,
        run_id=run_id,
        tenant_id=_principal.tenant_id,
        user_id=_principal.user_id,
        application_id=debug_app_id,
        conversation_id=payload.conversation_id,
        thread_id=payload.thread_id,
        on_node_event=_push_node_event,
        variables=debug_variables,
        user_variable_keys=debug_user_keys,
        on_user_variables_changed=debug_persist,
    )
    # 与用户端对话流一致：先发 run_start，前端据此拿到 thread/run/conversation
    await queue.put(sse_event("run_start", {
        "conversation_id": str(payload.conversation_id) if payload.conversation_id else None,
        "thread_id": runtime.thread_id,
        "run_id": str(runtime.run_id),
    }))

    async def runner_task() -> None:
        try:
            output = await runtime.invoke(payload.inputs)
            await queue.put(sse_event("result", {"outputs": output}))
        except GraphInterrupted as exc:
            await _push_interrupt(queue, exc, runtime)
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("debug stream failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner_task())

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


class DebugNodeRunPayload(BaseModel):
    """单节点试运行请求体。"""

    graph: dict[str, Any]
    node_id: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    conversation_id: UUID | None = None


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

    model_service = ModelService(uow.session)
    services = ServiceRegistry()
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, _principal.tenant_id)),
    )
    services.register("http", HttpService())

    run_id = uuid.uuid4()
    _register_conversation_services(
        services, uow, _principal,
        application_id=DEBUG_APPLICATION_ID, run_id=run_id,
    )
    _register_subgraph_loader(services, uow, _principal.tenant_id)

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


class DebugConversationPayload(BaseModel):
    """画布对话流试运行：创建一个 debug 会话。"""

    application_id: UUID
    title: str = Field("画布试运行", max_length=200)


@router.post("/debug/conversations", status_code=status.HTTP_201_CREATED)
def create_debug_conversation(
    payload: DebugConversationPayload,
    uow: UowDep,
    principal: PlatformAdminDep,
) -> dict:
    """为画布对话流试运行创建会话（channel=debug，不进入用户端会话列表）。"""
    if principal.tenant_id is None or principal.user_id is None:
        raise ValidationError("无法识别租户或用户")
    conversation_id = SyncConversationRepository(uow.session).insert_conversation(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        application_id=payload.application_id,
        title=payload.title,
        channel="debug",
    )
    uow.commit()
    return {"conversation_id": str(conversation_id)}


class DebugResumePayload(BaseModel):
    """人审 / 问答续跑请求体。"""

    graph: dict[str, Any]
    thread_id: str
    run_id: str | None = None
    conversation_id: UUID | None = None
    application_id: UUID | None = None
    # 人审批复：{"approved": bool, "comment": str, "approver": str}
    approval: dict[str, Any] | None = None
    # 问答节点回答等自由载荷：{"answer": "..."}
    resume: dict[str, Any] | None = None


@router.post("/debug/run/stream/resume")
async def debug_run_stream_resume(
    payload: DebugResumePayload,
    uow: UowDep,
    _principal: PlatformAdminDep,
) -> StreamingResponse:
    """人审 / 问答续跑：用 thread_id + Command(resume=...) 从 interrupt 点继续。"""
    nodes = payload.graph.get("nodes") or []
    if not isinstance(nodes, list) or len(nodes) > 50:
        raise ValidationError("graph 节点数必须在 1-50 之间")
    resume_value = payload.resume if payload.resume is not None else payload.approval
    if resume_value is None:
        raise ValidationError("续跑载荷不能为空")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    model_service = ModelService(uow.session)
    services = ServiceRegistry()
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, _principal.tenant_id)),
    )
    services.register("http", HttpService())

    run_id = uuid.UUID(payload.run_id) if payload.run_id else uuid.uuid4()
    debug_app_id = payload.application_id or DEBUG_APPLICATION_ID
    _register_conversation_services(
        services, uow, _principal,
        application_id=debug_app_id, run_id=run_id,
    )
    _register_subgraph_loader(services, uow, _principal.tenant_id)

    async def _push_node_event(etype: str, evt_payload: dict) -> None:
        await queue.put(sse_event(etype, evt_payload))

    debug_variables, debug_user_keys, debug_persist = _load_debug_variables(
        uow, payload.application_id, _principal,
    )
    runtime = GraphRuntime(
        canvas_json=payload.graph,
        services=services,
        thread_id=payload.thread_id,
        run_id=run_id,
        tenant_id=_principal.tenant_id,
        user_id=_principal.user_id,
        application_id=debug_app_id,
        conversation_id=payload.conversation_id,
        on_node_event=_push_node_event,
        variables=debug_variables,
        user_variable_keys=debug_user_keys,
        on_user_variables_changed=debug_persist,
    )
    await queue.put(sse_event("run_start", {
        "conversation_id": str(payload.conversation_id) if payload.conversation_id else None,
        "thread_id": runtime.thread_id,
        "run_id": str(runtime.run_id),
    }))

    async def runner_task() -> None:
        try:
            output = await runtime.resume(resume_value)
            await queue.put(sse_event("result", {"outputs": output}))
        except GraphInterrupted as exc:
            await _push_interrupt(queue, exc, runtime)
        except AppError as exc:
            await queue.put(sse_event("error", {"message": exc.message, "code": exc.status_code}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("debug resume stream failed")
            await queue.put(sse_event("error", {"message": str(exc), "code": 500}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner_task())

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
