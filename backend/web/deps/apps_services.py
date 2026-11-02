"""apps 上下文组合根工厂：具体仓储/缓存/配置的构造与注入集中在 web 层完成。

application/apps/* 服务只依赖 domain Protocol 端口，不 import infra 具体类；
本模块是唯一允许同时 import application 服务与 infra 仓储的装配点之一
（另一处 web/deps/graph.py 只 import 本模块的工厂函数，避免重复装配）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.apps.resource_service import AppResourceService
from internal.application.apps.tenant_settings_service import TenantSettingsService
from internal.infrastructure.cache.factory import get_kv_cache
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import MessageRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.resource_repository import AppResourceRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.tenant_settings_repository import (
    TenantSettingsRepository,
)
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


def make_app_resource_service(session: Session) -> AppResourceService:
    return AppResourceService(AppResourceRepository(session))


def make_tenant_settings_service(session: Session) -> TenantSettingsService:
    return TenantSettingsService(
        TenantSettingsRepository(session),
        ModelRepository(session),
        session,
    )


def make_conversation_repository(session: Session) -> ConversationRepository:
    return ConversationRepository(session)


def make_message_repository(session: Session) -> MessageRepository:
    return MessageRepository(session)


def make_run_repository(session: Session) -> RunRepository:
    return RunRepository(session)
