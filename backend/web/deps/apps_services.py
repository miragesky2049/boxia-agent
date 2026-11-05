"""apps 上下文组合根工厂：具体仓储/缓存/配置的构造与注入集中在 web 层完成。

application/apps/* 服务只依赖 domain Protocol 端口，不 import infra 具体类；
本模块是唯一允许同时 import application 服务与 infra 仓储的装配点之一
（另一处 web/deps/graph.py 只 import 本模块的工厂函数，避免重复装配）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.conversation_admin_service import ConversationAdminService
from internal.application.apps.model_service import ModelService
from internal.application.apps.resource_service import AppResourceService
from internal.application.apps.run_service import RunService
from internal.application.apps.tenant_settings_service import TenantSettingsService
from internal.application.apps.webhook_service import WebhookService
from internal.application.apps.workflow_service import WorkflowService
from internal.domain.auth.apply_service import ApplyService
from internal.domain.auth.grant_service import GrantService
from internal.domain.auth.service import AuthService
from internal.infrastructure.cache.factory import get_kv_cache
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import MessageRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.resource_repository import AppResourceRepository
from internal.infrastructure.repository.apps.resource_type_catalog_repository import (
    ResourceTypeCatalogRepository,
)
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.tenant_settings_repository import (
    TenantSettingsRepository,
)
from internal.infrastructure.repository.apps.webhook_repository import WebhookRepository
from internal.infrastructure.storage.factory import get_object_storage


def make_application_service(uow: SqlAlchemyUnitOfWork) -> ApplicationService:
    """构造 ApplicationService：仓储/Redis 缓存/对象存储/默认模型 ID 全部注入。"""
    return ApplicationService(
        uow,
        ApplicationRepository(uow.session),
        cache=get_kv_cache(),
        object_storage=get_object_storage(),
        default_llm_model_id=get_settings().llm_model_id,
    )


def make_model_service(session: Session) -> ModelService:
    return ModelService(ModelRepository(session))


def make_app_resource_service(uow: SqlAlchemyUnitOfWork) -> AppResourceService:
    """资源服务：裸 SQL 仓储 + 请求级 UoW（审核审计共享事务）+ 类型注册表读侧（P3-5）。"""
    return AppResourceService(
        AppResourceRepository(uow.session), uow, ResourceTypeCatalogRepository(uow.session)
    )


def make_tenant_settings_service(session: Session) -> TenantSettingsService:
    return TenantSettingsService(
        TenantSettingsRepository(session),
        ModelRepository(session),
        session,
    )


def make_conversation_admin_service(uow: SqlAlchemyUnitOfWork) -> ConversationAdminService:
    """admin 会话排查服务：session-per-repo 仓储 + 请求级 UoW 提交。"""
    return ConversationAdminService(
        uow.commit,
        ConversationRepository(uow.session),
        MessageRepository(uow.session),
    )


def make_run_service(uow: SqlAlchemyUnitOfWork) -> RunService:
    """运行审计查询服务（只读 + fork 落记录，提交策略见 RunService docstring）。"""
    return RunService(RunRepository(uow.session))


def make_webhook_service(uow: SqlAlchemyUnitOfWork) -> WebhookService:
    """webhook 订阅服务：CRUD + SSRF 校验收口。"""
    return WebhookService(uow.commit, WebhookRepository(uow.session))


def make_apply_service(uow: SqlAlchemyUnitOfWork) -> ApplyService:
    """申请单服务装配（原 applies router 内 _build_apply_service 收口至组合根）。"""
    repo = AuthRepository(uow.session)
    auth_service = AuthService(repo, cache=None)
    grant_service = GrantService(repo, auth_service)
    return ApplyService(repo, auth_service, grant_service)


def make_conversation_repository(session: Session) -> ConversationRepository:
    return ConversationRepository(session)


def make_message_repository(session: Session) -> MessageRepository:
    return MessageRepository(session)


def make_run_repository(session: Session) -> RunRepository:
    return RunRepository(session)


def make_workflow_service(uow: SqlAlchemyUnitOfWork, principal: object) -> WorkflowService:
    """用户端 workflow 编排服务装配：runner_factory 延迟 import 避免与 web/deps/graph.py 循环。"""
    from web.deps.graph import build_runner

    return WorkflowService(
        uow=uow,
        principal=principal,
        runner_factory=build_runner,
        app_service=make_application_service(uow),
        run_repo=RunRepository(uow.session),
    )
