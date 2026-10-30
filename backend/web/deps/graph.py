"""GraphRuntime 组装 helper：admin / user 端共用。

从老 GraphRunner 迁移到 domain/graph 新引擎（GraphRuntime）。
调用方负责：鉴权、可见性/授权校验、uow.commit()。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.apps.resource_service import AppResourceService
from internal.application.retrieval_service import RetrievalService
from internal.domain.graph.node_base import ServiceRegistry
from internal.engine.runtime import GraphRuntime
from internal.engine.services.http_service import HttpService
from internal.engine.services.llm_adapter import (
    LLMServiceAdapter,
    build_model_resolver,
)
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.usage_repository import UsageRepository
from internal.infrastructure.repository.apps.webhook_repository import WebhookRepository
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)

logger = logging.getLogger(__name__)


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
) -> GraphRuntime:
    """构造 GraphRuntime：加载 coze 画布 JSON + 注册 llm/http/subgraph_loader 服务。

    - canvas_json 走 ApplicationService.get_runtime_graph（Redis 缓存 + 租户 pin/config 覆盖）
    - thread_id 由调用方传入；不传时由 runtime 内部生成
    - run_id 不传时由 runtime 内部生成
    """
    canvas_json = await service.get_runtime_graph(application_id, tenant_id)
    model_service = ModelService(uow.session)
    resource_service = AppResourceService(uow.session)

    run_repo = RunRepository(uow.session)
    usage_repo = UsageRepository(uow.session)
    audit_repo = PostgresAuditLogRepository(uow.session)
    webhook_repo = WebhookRepository(uow.session)

    # 构造服务注册表：llm / http / subgraph_loader
    services = ServiceRegistry()
    services.register(
        "llm",
        LLMServiceAdapter(build_model_resolver(model_service, tenant_id)),
    )
    services.register("http", HttpService())

    async def subgraph_loader(child_app_id: str) -> dict:
        try:
            child_uuid = UUID(child_app_id)
        except ValueError:
            return {}
        try:
            return await service.get_runtime_graph(child_uuid, tenant_id)
        except Exception:  # noqa: BLE001
            logger.exception("加载子图失败: child_app_id=%s", child_app_id)
            return {}

    services.register("subgraph_loader", subgraph_loader)

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
        run_id=run_id,
        actor_username=actor_username,
    )
