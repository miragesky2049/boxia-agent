"""应用服务依赖装配：Web 层通过 Depends 获取用例。"""

from typing import Annotated

from fastapi import Depends

from internal.application.admin_user_service import AdminUserService, AuditService
from internal.application.agent_service import AgentService
from internal.application.auth_service import AuthService
from internal.application.grant_service import GrantService
from internal.application.resource_service import ResourceService
from internal.application.role_grant_service import RoleGrantService
from internal.application.role_permission_service import RolePermissionService
from internal.application.role_service import RoleService
from internal.application.skill_package_service import SkillPackageService
from internal.application.skill_service import SkillService
from internal.application.tenant_service import TenantService
from internal.application.user_admin_service import UserAdminService
from internal.application.user_auth_service import UserAuthService
from internal.application.user_portal_service import UserPortalService
from internal.domain.entity.resource import Component, Prompt, Tool
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from web.deps.db import UowDep
from web.deps.scoped import AdminScopedUowDep, UserScopedUowDep
from web.deps.tenant import RequestContextDep


def get_auth_service(uow: UowDep) -> AuthService:
    """管理员认证用例。"""
    return AuthService(uow)


def get_user_auth_service(uow: UowDep) -> UserAuthService:
    """最终用户认证用例。"""
    return UserAuthService(uow)


def get_agent_service(uow: AdminScopedUowDep, context: RequestContextDep) -> AgentService:
    """智能体用例。"""
    return AgentService(uow, context)


def get_skill_service(uow: AdminScopedUowDep, context: RequestContextDep) -> SkillService:
    """技能用例（含 SKILL.md 同步）。"""
    return SkillService(uow.skills, "技能", "skill", uow, context)


def get_skill_package_service(
    uow: AdminScopedUowDep, context: RequestContextDep
) -> SkillPackageService:
    """技能包文件读写、导入导出与克隆用例。"""
    return SkillPackageService(uow, context)


def get_tool_service(uow: AdminScopedUowDep, context: RequestContextDep) -> ResourceService[Tool]:
    """工具用例。"""
    return ResourceService(uow.tools, "工具", "tool", uow, context)


def get_component_service(
    uow: AdminScopedUowDep, context: RequestContextDep
) -> ResourceService[Component]:
    """组件用例。"""
    return ResourceService(uow.components, "组件", "component", uow, context)


def get_prompt_service(
    uow: AdminScopedUowDep, context: RequestContextDep
) -> ResourceService[Prompt]:
    """提示词用例。"""
    return ResourceService(uow.prompts, "提示词", "prompt", uow, context)


def get_admin_user_service(uow: UowDep, context: RequestContextDep) -> AdminUserService:
    """管理员账号管理用例。"""
    return AdminUserService(uow, context)


def get_audit_service(uow: UowDep, context: RequestContextDep) -> AuditService:
    """审计日志查询用例。"""
    return AuditService(uow, context)


def get_tenant_service(uow: UowDep, context: RequestContextDep) -> TenantService:
    """租户管理用例。"""
    return TenantService(uow, context)


def get_role_service(uow: UowDep, context: RequestContextDep) -> RoleService:
    """租户角色管理用例。"""
    return RoleService(uow, context)


def get_role_grant_service(uow: UowDep, context: RequestContextDep) -> RoleGrantService:
    """角色授权明细用例。"""
    return RoleGrantService(uow, context)


def get_role_permission_service(uow: UowDep, context: RequestContextDep) -> RolePermissionService:
    """角色功能权限用例。"""
    return RolePermissionService(uow, context)


def get_user_service(uow: UowDep, context: RequestContextDep) -> UserAdminService:
    """最终用户管理用例。"""
    return UserAdminService(uow, context)


def get_grant_service(uow: AdminScopedUowDep, context: RequestContextDep) -> GrantService:
    """资源授权用例。"""
    return GrantService(uow, context)


def get_user_portal_service(uow: UserScopedUowDep, context: RequestContextDep) -> UserPortalService:
    """用户端智能体查询用例。"""
    return UserPortalService(uow, context)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserAuthServiceDep = Annotated[UserAuthService, Depends(get_user_auth_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]
SkillPackageServiceDep = Annotated[SkillPackageService, Depends(get_skill_package_service)]
ToolServiceDep = Annotated[ResourceService[Tool], Depends(get_tool_service)]
ComponentServiceDep = Annotated[ResourceService[Component], Depends(get_component_service)]
PromptServiceDep = Annotated[ResourceService[Prompt], Depends(get_prompt_service)]
AdminUserServiceDep = Annotated[AdminUserService, Depends(get_admin_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]
RoleGrantServiceDep = Annotated[RoleGrantService, Depends(get_role_grant_service)]
RolePermissionServiceDep = Annotated[RolePermissionService, Depends(get_role_permission_service)]
UserAdminServiceDep = Annotated[UserAdminService, Depends(get_user_service)]
GrantServiceDep = Annotated[GrantService, Depends(get_grant_service)]
UserPortalServiceDep = Annotated[UserPortalService, Depends(get_user_portal_service)]

# 类型导出：路由中用于显式标注依赖返回值
__all__ = [
    "AdminUserServiceDep",
    "AgentServiceDep",
    "AuditServiceDep",
    "AuthServiceDep",
    "ComponentServiceDep",
    "UserAdminServiceDep",
    "GrantServiceDep",
    "PromptServiceDep",
    "RoleGrantServiceDep",
    "RolePermissionServiceDep",
    "RoleServiceDep",
    "SkillPackageServiceDep",
    "SkillServiceDep",
    "TenantServiceDep",
    "ToolServiceDep",
    "UserAuthServiceDep",
    "UserPortalServiceDep",
    "SqlAlchemyUnitOfWork",
]
