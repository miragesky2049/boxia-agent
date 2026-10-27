"""SQLAlchemy 工作单元实现：统一管理会话、仓储与事务边界。"""

from uuid import UUID

from sqlalchemy.orm import Session

from internal.domain.entity.data_scope import UserDataScope
from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from internal.domain.repository.protocols import (
    AdminUserRepository,
    AgentRepository,
    AgentTenantOpeningRepository,
    AuditLogRepository,
    DepartmentRepository,
    EmploymentRepository,
    HrDictionaryRepository,
    MgmtUnitRepository,
    PermissionResourceRepository,
    RefreshTokenRepository,
    ResourceGrantRepository,
    ResourceRepository,
    RolePermissionRepository,
    RoleRepository,
    SkillFileRepository,
    TenantRepository,
    UserMgmtUnitGrantRepository,
    UserRefreshTokenRepository,
    UserRepository,
)
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.agent_user_visibility_filter import (
    UserAgentVisibilityContext,
)
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
from internal.infrastructure.repository.postgres_hr_dictionary_repository import (
    PostgresHrDictionaryRepository,
)
from internal.infrastructure.repository.postgres_mgmt_unit_repository import (
    PostgresMgmtUnitRepository,
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
from internal.infrastructure.repository.postgres_user_mgmt_unit_grant_repository import (
    PostgresUserMgmtUnitGrantRepository,
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
        self.hr_dictionaries: HrDictionaryRepository = PostgresHrDictionaryRepository(
            self.session
        )
        self.mgmt_units: MgmtUnitRepository = PostgresMgmtUnitRepository(self.session)
        self.user_mgmt_unit_grants: UserMgmtUnitGrantRepository = (
            PostgresUserMgmtUnitGrantRepository(self.session)
        )
        self.resource_grants: ResourceGrantRepository = PostgresResourceGrantRepository(
            self.session
        )
        # 角色过滤与行级数据范围在仓储重建时合并携带，apply_* 两者叠加生效
        self._scope_role_ids: tuple[UUID, ...] = ()
        self._scope_apply_role_filter: bool = True
        self._data_scope_snapshot: UserDataScope | None = None
        self._user_visibility: UserAgentVisibilityContext | None = None
        # user 端门户模式：注入实例级可见范围时同步打开，用于跳过角色授权收敛
        self._user_portal: bool = False
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
        self._scope_role_ids = tuple(role_ids)
        self._scope_apply_role_filter = apply_role_filter
        self._rebuild_agent_repo()
        self.skills = PostgresSkillRepository(
            self.session, self.tenant_id, self._scope_role_ids, self._scope_apply_role_filter
        )
        self.tools = PostgresToolRepository(
            self.session, self.tenant_id, self._scope_role_ids, self._scope_apply_role_filter
        )
        self.components = PostgresComponentRepository(
            self.session, self.tenant_id, self._scope_role_ids, self._scope_apply_role_filter
        )
        self.prompts = PostgresPromptRepository(
            self.session, self.tenant_id, self._scope_role_ids, self._scope_apply_role_filter
        )

    def apply_data_scope(self, snapshot: UserDataScope | None = None) -> None:
        """按行级数据权限快照重建智能体仓储；None 表示清除叠加的行过滤。"""
        self._data_scope_snapshot = snapshot
        self._rebuild_agent_repo()

    def apply_user_visibility(self, context: UserAgentVisibilityContext | None = None) -> None:
        """按 user 端实例级可见范围重建智能体仓储；None 表示清除叠加。

        注入 user_visibility 时自动开启 user 端门户模式：跳过角色授权收敛，
        由部门/人员实例级 ACL 作为唯一细粒度判断；context=None 时一并关闭。
        """
        self._user_visibility = context
        self._user_portal = context is not None
        self._rebuild_agent_repo()

    def _rebuild_agent_repo(self) -> None:
        """以角色过滤状态 + 行级数据范围 + user 端可见范围统一重建智能体仓储。"""
        self.agents = PostgresAgentRepository(
            self.session,
            self.tenant_id,
            self._scope_role_ids,
            self._scope_apply_role_filter,
            self._data_scope_snapshot,
            self._user_visibility,
            self._user_portal,
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
