"""SQLAlchemy 工作单元实现：统一管理会话、仓储与事务边界。"""

from uuid import UUID

from sqlalchemy.orm import Session

from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from internal.domain.repository.protocols import (
    AdminUserRepository,
    AgentRepository,
    AgentTenantOpeningRepository,
    AuditLogRepository,
    DepartmentRepository,
    EmploymentRepository,
    PermissionResourceRepository,
    RefreshTokenRepository,
    ResourceGrantRepository,
    ResourceRepository,
    RolePermissionRepository,
    RoleRepository,
    SkillFileRepository,
    TenantRepository,
    UserRefreshTokenRepository,
    UserRepository,
)
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.postgres_admin_user_repository import (
    PostgresAdminUserRepository,
)
from internal.infrastructure.repository.postgres_agent_repository import PostgresAgentRepository
from internal.infrastructure.repository.postgres_agent_tenant_opening_repository import (
    PostgresAgentTenantOpeningRepository,
)
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)
from internal.infrastructure.repository.postgres_department_repository import (
    PostgresDepartmentRepository,
)
from internal.infrastructure.repository.postgres_employment_repository import (
    PostgresEmploymentRepository,
)
from internal.infrastructure.repository.postgres_permission_resource_repository import (
    PostgresPermissionResourceRepository,
)
from internal.infrastructure.repository.postgres_refresh_token_repository import (
    PostgresRefreshTokenRepository,
)
from internal.infrastructure.repository.postgres_resource_grant_repository import (
    PostgresResourceGrantRepository,
)
from internal.infrastructure.repository.postgres_resource_repository import (
    PostgresComponentRepository,
    PostgresPromptRepository,
    PostgresSkillRepository,
    PostgresToolRepository,
)
from internal.infrastructure.repository.postgres_role_permission_repository import (
    PostgresRolePermissionRepository,
)
from internal.infrastructure.repository.postgres_role_repository import PostgresRoleRepository
from internal.infrastructure.repository.postgres_skill_file_repository import (
    PostgresSkillFileRepository,
)
from internal.infrastructure.repository.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from internal.infrastructure.repository.postgres_user_refresh_token_repository import (
    PostgresUserRefreshTokenRepository,
)
from internal.infrastructure.repository.postgres_user_repository import (
    PostgresUserRepository,
)


class SqlAlchemyUnitOfWork:
    """请求级工作单元，应用服务通过它提交业务事务。"""

    def __init__(self, tenant_id: UUID | None = None) -> None:
        # tenant_id 为 None 表示产品级平台上下文，非空表示租户级上下文。
        self.tenant_id = tenant_id
        self.session: Session = get_session_factory()()
        self.tenants: TenantRepository = PostgresTenantRepository(self.session)
        self.admin_users: AdminUserRepository = PostgresAdminUserRepository(self.session)
        self.refresh_tokens: RefreshTokenRepository = PostgresRefreshTokenRepository(self.session)
        self.audit_logs: AuditLogRepository = PostgresAuditLogRepository(self.session)
        self.roles: RoleRepository = PostgresRoleRepository(self.session)
        self.permission_resources: PermissionResourceRepository = (
            PostgresPermissionResourceRepository(self.session)
        )
        self.role_permissions: RolePermissionRepository = PostgresRolePermissionRepository(
            self.session
        )
        self.users: UserRepository = PostgresUserRepository(self.session)
        self.user_refresh_tokens: UserRefreshTokenRepository = PostgresUserRefreshTokenRepository(
            self.session
        )
        self.departments: DepartmentRepository = PostgresDepartmentRepository(self.session)
        self.employments: EmploymentRepository = PostgresEmploymentRepository(self.session)
        self.resource_grants: ResourceGrantRepository = PostgresResourceGrantRepository(
            self.session
        )
        self.agents: AgentRepository = PostgresAgentRepository(self.session, tenant_id)
        # 开通关系不参与角色收敛，租户侧查询由应用层按需过滤。
        self.agent_openings: AgentTenantOpeningRepository = PostgresAgentTenantOpeningRepository(
            self.session
        )
        self.skills: ResourceRepository[Skill] = PostgresSkillRepository(self.session, tenant_id)
        self.skill_files: SkillFileRepository = PostgresSkillFileRepository(self.session)
        self.tools: ResourceRepository[Tool] = PostgresToolRepository(self.session, tenant_id)
        self.components: ResourceRepository[Component] = PostgresComponentRepository(
            self.session, tenant_id
        )
        self.prompts: ResourceRepository[Prompt] = PostgresPromptRepository(self.session, tenant_id)

    def apply_scope(self, role_ids: tuple[UUID, ...] = (), apply_role_filter: bool = True) -> None:
        """按当前账号角色重建资源与智能体仓储，其余仓储复用同一会话。"""
        self.agents = PostgresAgentRepository(
            self.session, self.tenant_id, role_ids, apply_role_filter
        )
        self.skills = PostgresSkillRepository(
            self.session, self.tenant_id, role_ids, apply_role_filter
        )
        self.tools = PostgresToolRepository(
            self.session, self.tenant_id, role_ids, apply_role_filter
        )
        self.components = PostgresComponentRepository(
            self.session, self.tenant_id, role_ids, apply_role_filter
        )
        self.prompts = PostgresPromptRepository(
            self.session, self.tenant_id, role_ids, apply_role_filter
        )

    def commit(self) -> None:
        """提交当前事务。"""
        self.session.commit()

    def rollback(self) -> None:
        """回滚当前事务。"""
        self.session.rollback()

    def close(self) -> None:
        """关闭会话。"""
        self.session.close()
