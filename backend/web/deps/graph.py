"""GraphRuntime 组装 helper：admin / user 端共用。

从老 GraphRunner 迁移到 domain/graph 新引擎（GraphRuntime）。
调用方负责：鉴权、可见性/授权校验、uow.commit()。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from internal.application.apps.application_service import ApplicationService
from internal.application.retrieval_service import RetrievalService
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.graph.runtime import GraphRuntime
from internal.domain.graph.http_service import HttpService
from internal.domain.llm.adapter import (
    LLMServiceAdapter,
    build_model_resolver,
)
from internal.domain.agent.tool_executor import ToolExecutorService
from internal.infrastructure.retrieval.factory import register_retrieval_services
from internal.infrastructure.sandbox.python_sandbox import PythonSandbox
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.usage_repository import UsageRepository
from internal.infrastructure.repository.apps.webhook_repository import WebhookRepository
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
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)
from internal.infrastructure.repository.postgres_resource_repository import (
    PostgresToolRepository,
)
from web.deps.apps_services import make_application_service, make_model_service

logger = logging.getLogger(__name__)


def register_llm_and_http(services: ServiceRegistry, uow: Any, tenant_id: Any) -> None:
    """注册 llm / http 基础服务（build_runner 与 admin debug 画布试运行共用装配）。

    tenant_id 允许为 None：与迁移前 apps_admin debug 端点的直传行为保持一致。
    """
    model_service = make_model_service(uow.session)
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, tenant_id)),
    )
    services.register("http", HttpService())


def register_conversation_services(
    services: ServiceRegistry,
    uow: Any,
    *,
    tenant_id: UUID | None,
    user_id: UUID | None,
    application_id: UUID,
    run_id: UUID | str,
    enforce_application: bool = False,
) -> None:
    """把会话/消息仓储 + tool_executor + retrieval + sandbox 注册进 ServiceRegistry。

    admin 画布试运行专用（DDD 三期从 apps_admin 收敛至此）：
    试运行没有真实应用 ID（application_id 可为 DEBUG_APPLICATION_ID），
    默认不校验应用维度，只按租户 + 用户收口，避免消息节点写入真实应用会话时报"不属于当前应用"。
    tenant_id 缺失时兜底平台租户（与原 apps_admin helper 行为一致）。
    """
    effective_tenant_id = tenant_id or PLATFORM_TENANT_ID
    conv_repo = AsyncConversationRepository(
        SyncConversationRepository(uow.session),
        tenant_id=effective_tenant_id,
        user_id=user_id,
        application_id=application_id,
        enforce_application=enforce_application,
        channel="debug",
    )
    # 试运行不写 run 表，消息的 run_id 必须留空，否则触发 run 外键约束
    msg_repo = AsyncMessageRepository(
        SyncMessageRepository(uow.session),
        tenant_id=effective_tenant_id,
        user_id=user_id,
        application_id=application_id,
        run_id=None,
        enforce_application=enforce_application,
    )
    services.register("conversation_repo", conv_repo)
    services.register("message_repo", msg_repo)
    services.register(
        "tool_executor",
        ToolExecutorService(
            PostgresToolRepository(
                uow.session,
                tenant_id=effective_tenant_id,
                apply_role_filter=False,
            ),
            tenant_id=effective_tenant_id,
            user_id=user_id,
            application_id=application_id,
            run_id=run_id,
        ),
    )
    register_retrieval_services(services)
    services.register("sandbox", PythonSandbox())


def register_subgraph_loader(
    services: ServiceRegistry, service: ApplicationService, tenant_id: Any,
) -> None:
    """注册 subgraph_loader，供 Subworkflow（type=9）节点按 tenant 加载子应用 runtime graph。"""

    async def _loader(child_app_id: str) -> dict:
        try:
            child_uuid = UUID(child_app_id)
        except ValueError:
            return {}
        try:
            return await service.get_runtime_graph(child_uuid, tenant_id)
        except Exception:  # noqa: BLE001
            logger.exception("加载子图失败: child_app_id=%s", child_app_id)
            return {}

    services.register("subgraph_loader", _loader)


def load_debug_variables(
    uow: Any,
    application_id: UUID | None,
    principal: Any,
) -> tuple[dict[str, Any], set[str], Any]:
    """画布试运行使用真实应用的变量定义；未指定应用时返回空池。"""
    if application_id is None or principal.user_id is None:
        return {}, set(), None
    try:
        variables, user_keys = make_application_service(uow).build_runtime_variables(
            application_id, principal.user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("加载画布试运行变量失败 application=%s", application_id)
        return {}, set(), None
    repo = ApplicationRepository(uow.session)

    def _persist(values: dict[str, Any]) -> None:
        repo.set_user_variables(application_id, principal.user_id, values)

    return variables, user_keys, _persist


def make_canvas_debug_runtime(
    uow: Any,
    principal: Any,
    *,
    graph: dict[str, Any],
    application_id: UUID,
    variables_application_id: UUID | None,
    run_id: UUID,
    conversation_id: UUID | None,
    thread_id: str | None,
    on_node_event: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> GraphRuntime:
    """画布试运行 GraphRuntime 装配（CanvasDebugRuntimeFactory 端口的组合根实现）。

    与迁移前 apps_admin router 内联装配逐参数等价：直接用前端未保存 graph，
    conversation/message 挂 debug 应用 ID，变量按 variables_application_id（可空）加载。
    """
    services = ServiceRegistry()
    register_llm_and_http(services, uow, principal.tenant_id)
    register_conversation_services(
        services, uow,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        application_id=application_id,
        run_id=run_id,
    )
    register_subgraph_loader(services, make_application_service(uow), principal.tenant_id)
    debug_variables, debug_user_keys, debug_persist = load_debug_variables(
        uow, variables_application_id, principal,
    )
    return GraphRuntime(
        canvas_json=graph,
        services=services,
        run_id=run_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        application_id=application_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        on_node_event=on_node_event,
        variables=debug_variables,
        user_variable_keys=debug_user_keys,
        on_user_variables_changed=debug_persist,
    )


async def build_runner(
    service: ApplicationService,
    uow: Any,
    context: Any,
    *,
    tenant_id: UUID,
    application_id: UUID,
    thread_id: str | None = None,
    run_id: UUID | None = None,
    current_user_id: UUID | None = None,
    actor_username: str | None = None,
    conversation_id: UUID | None = None,
    on_node_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> GraphRuntime:
    """构造 GraphRuntime：加载 coze 画布 JSON + 注册 llm/http/subgraph_loader 服务。

    - canvas_json 走 ApplicationService.get_runtime_graph（Redis 缓存 + 租户 pin/config 覆盖）
    - thread_id 由调用方传入；不传时由 runtime 内部生成
    - run_id 不传时由 runtime 内部生成
    """
    canvas_json = await service.get_runtime_graph(application_id, tenant_id)
    app_repo = ApplicationRepository(uow.session)

    # 变量体系：应用变量取默认值，用户变量优先取当前用户已持久化的值
    try:
        runtime_variables, user_variable_keys = service.build_runtime_variables(
            application_id, current_user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("加载应用变量失败 application=%s", application_id)
        runtime_variables, user_variable_keys = {}, set()

    # run_id 只生成一次：runtime、tool_executor、message_repo 共用，
    # 保证本轮 run / 节点消息 / 最终回答的审计字段一致。
    effective_run_id = run_id or uuid4()

    def _persist_user_variables(values: dict[str, Any]) -> None:
        if current_user_id is None:
            return
        app_repo.set_user_variables(application_id, current_user_id, values)

    run_repo = RunRepository(uow.session)
    usage_repo = UsageRepository(uow.session)
    audit_repo = PostgresAuditLogRepository(uow.session)
    webhook_repo = WebhookRepository(uow.session)

    # 构造服务注册表：llm / http / tool_executor / retrieval / sandbox / subgraph_loader
    services = ServiceRegistry()
    register_llm_and_http(services, uow, tenant_id)
    services.register(
        "tool_executor",
        ToolExecutorService(
            PostgresToolRepository(
                uow.session,
                tenant_id=tenant_id,
                apply_role_filter=False,
            ),
            tenant_id=tenant_id,
            user_id=current_user_id,
            application_id=application_id,
            run_id=effective_run_id,
        ),
    )
    register_retrieval_services(services)
    services.register("sandbox", PythonSandbox())

    # conversation / message 节点（38/39/51-57）依赖的异步仓储。
    # user 端 current_user_id 必传；admin debug 路由走 _register_conversation_services 单独绑定。
    if current_user_id is not None:
        async_conv_repo = AsyncConversationRepository(
            SyncConversationRepository(uow.session),
            tenant_id=tenant_id,
            user_id=current_user_id,
            application_id=application_id,
        )
        async_msg_repo = AsyncMessageRepository(
            SyncMessageRepository(uow.session),
            tenant_id=tenant_id,
            user_id=current_user_id,
            application_id=application_id,
            run_id=effective_run_id,
        )
        services.register("conversation_repo", async_conv_repo)
        services.register("message_repo", async_msg_repo)

    register_subgraph_loader(services, service, tenant_id)

    return GraphRuntime(
        canvas_json=canvas_json,
        services=services,
        run_repo=run_repo,
        usage_repo=usage_repo,
        audit_repo=audit_repo,
        webhook_repo=webhook_repo,
        tenant_id=tenant_id,
        user_id=current_user_id,
        application_id=application_id,
        thread_id=thread_id,
        run_id=effective_run_id,
        actor_username=actor_username,
        conversation_id=conversation_id,
        on_node_event=on_node_event,
        variables=runtime_variables,
        user_variable_keys=user_variable_keys,
        on_user_variables_changed=_persist_user_variables if current_user_id else None,
    )
