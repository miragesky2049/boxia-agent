"""SQLAlchemy 工作单元实现：统一管理会话、仓储与事务边界。"""

from sqlalchemy.orm import Session

from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from internal.domain.repository.protocols import (
    AdminUserRepository,
    AgentRepository,
    AuditLogRepository,
    RefreshTokenRepository,
    ResourceRepository,
    TenantRepository,
)
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.postgres_admin_user_repository import (
    PostgresAdminUserRepository,
)
from internal.infrastructure.repository.postgres_agent_repository import PostgresAgentRepository
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)
from internal.infrastructure.repository.postgres_refresh_token_repository import (
    PostgresRefreshTokenRepository,
)
from internal.infrastructure.repository.postgres_resource_repository import (
    PostgresComponentRepository,
    PostgresPromptRepository,
    PostgresSkillRepository,
    PostgresToolRepository,
)
from internal.infrastructure.repository.postgres_tenant_repository import (
    PostgresTenantRepository,
)


class SqlAlchemyUnitOfWork:
    """请求级工作单元，应用服务通过它提交业务事务。"""

    def __init__(self, tenant_id: int | None = None) -> None:
        # tenant_id 为 None 表示产品级平台上下文，非空表示租户级上下文。
        self.tenant_id = tenant_id
        self.session: Session = get_session_factory()()
        self.tenants: TenantRepository = PostgresTenantRepository(self.session)
        self.admin_users: AdminUserRepository = PostgresAdminUserRepository(self.session)
        self.refresh_tokens: RefreshTokenRepository = PostgresRefreshTokenRepository(self.session)
        self.audit_logs: AuditLogRepository = PostgresAuditLogRepository(self.session)
        self.agents: AgentRepository = PostgresAgentRepository(self.session, tenant_id)
        self.skills: ResourceRepository[Skill] = PostgresSkillRepository(self.session, tenant_id)
        self.tools: ResourceRepository[Tool] = PostgresToolRepository(self.session, tenant_id)
        self.components: ResourceRepository[Component] = PostgresComponentRepository(
            self.session, tenant_id
        )
        self.prompts: ResourceRepository[Prompt] = PostgresPromptRepository(self.session, tenant_id)

    def commit(self) -> None:
        """提交当前事务。"""
        self.session.commit()

    def rollback(self) -> None:
        """回滚当前事务。"""
        self.session.rollback()

    def close(self) -> None:
        """关闭会话。"""
        self.session.close()
