"""SQLAlchemy 工作单元实现：统一管理会话、仓储与事务边界。"""

from uuid import UUID

from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.resource import Tool
from internal.domain.repository.protocols import (
    AdminUserRepository,
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
    TenantRepository,
    UserMgmtUnitGrantRepository,
    UserRefreshTokenRepository,
    UserRepository,
)
from internal.infrastructure.model.database import get_session_factory
from internal.infrastructure.repository.postgres_admin_user_repository import (
    PostgresAdminUserRepository,
)
from internal.infrastructure.repository.postgres_audit_log_repository import (
    PostgresAuditLogRepository,
)
from internal.infrastructure.repository.postgres_department_repository import (
    PostgresDepartmentRepository,
)
from internal.infrastructure.repository.postgres_document_repository import (
    PostgresDocumentChunkRepository,
    PostgresDocumentRepository,
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
from internal.infrastructure.repository.postgres_role_permission_repository import (
    PostgresRolePermissionRepository,
)
from internal.infrastructure.repository.postgres_role_repository import (
    PostgresRoleRepository,
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
from internal.infrastructure.repository.resource_tool_repository import (
    ResourceToolRepository,
)


class SqlAlchemyUnitOfWork:
    """请求级工作单元，应用服务通过它提交业务事务。"""

    def __init__(self, tenant_id: UUID | None = None) -> None:
        # tenant_id 为 None 视为产品级上下文，归一化为 PLATFORM_TENANT_ID（全零 UUID）。
        self.tenant_id: UUID = tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
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
        self._scope_role_ids: tuple[UUID, ...] = ()
        self._scope_apply_role_filter: bool = True
        self.tools: ResourceRepository[Tool] = ResourceToolRepository(self.session, tenant_id)
        # RAG 知识库：文档元数据 + 分块向量仓储
        self.documents = PostgresDocumentRepository(self.session, tenant_id)
        self.document_chunks = PostgresDocumentChunkRepository(self.session, tenant_id)

    def apply_scope(
        self, role_ids: tuple[UUID, ...] = (), apply_role_filter: bool = True
    ) -> None:
        """按当前账号角色重建资源仓储。"""
        self._scope_role_ids = tuple(role_ids)
        self._scope_apply_role_filter = apply_role_filter
        self.tools = ResourceToolRepository(
            self.session, self.tenant_id, self._scope_role_ids, self._scope_apply_role_filter
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
