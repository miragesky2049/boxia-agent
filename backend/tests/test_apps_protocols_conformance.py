"""apps 仓储 Protocol 结构符合性检查。

Protocol 与 infra 裸类的匹配是编译期约束：本文件的赋值语句由 mypy 静态校验
（infra 类缺方法/签名不兼容即报错），运行时只要求构造函数可调用。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from internal.domain.repository.apps_protocols import (
    ApplicationRepositoryProtocol,
    AppGrantRepositoryProtocol,
    AppResourceRepositoryProtocol,
    AuthRepositoryProtocol,
    ConversationRepositoryProtocol,
    MessageRepositoryProtocol,
    ModelRepositoryProtocol,
    RunRepositoryProtocol,
    TenantSettingsRepositoryProtocol,
    UsageRepositoryProtocol,
    WebhookRepositoryProtocol,
)
from internal.infrastructure.repository.apps.app_grant_repository import AppGrantRepository
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from internal.infrastructure.repository.apps.conversation_repository import ConversationRepository
from internal.infrastructure.repository.apps.message_repository import MessageRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.resource_repository import AppResourceRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from internal.infrastructure.repository.apps.tenant_settings_repository import (
    TenantSettingsRepository,
)
from internal.infrastructure.repository.apps.usage_repository import UsageRepository
from internal.infrastructure.repository.apps.webhook_repository import WebhookRepository


def test_infra_repositories_structurally_satisfy_protocols() -> None:
    session = MagicMock(name="session")

    app_repo: ApplicationRepositoryProtocol = ApplicationRepository(session)
    app_grant_repo: AppGrantRepositoryProtocol = AppGrantRepository(session)
    model_repo: ModelRepositoryProtocol = ModelRepository(session)
    conv_repo: ConversationRepositoryProtocol = ConversationRepository(session)
    msg_repo: MessageRepositoryProtocol = MessageRepository(session)
    run_repo: RunRepositoryProtocol = RunRepository(session)
    usage_repo: UsageRepositoryProtocol = UsageRepository(session)
    webhook_repo: WebhookRepositoryProtocol = WebhookRepository(session)
    resource_repo: AppResourceRepositoryProtocol = AppResourceRepository(session)
    auth_repo: AuthRepositoryProtocol = AuthRepository(session)
    tenant_settings_repo: TenantSettingsRepositoryProtocol = TenantSettingsRepository(session)

    assert all(
        r is not None
        for r in (
            app_repo, app_grant_repo, model_repo, conv_repo, msg_repo, run_repo,
            usage_repo, webhook_repo, resource_repo, auth_repo, tenant_settings_repo,
        )
    )
