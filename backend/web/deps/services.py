"""应用服务依赖装配：Web 层通过 Depends 获取用例。"""

from typing import Annotated

from fastapi import Depends

from internal.application.admin_user_service import AdminUserService, AuditService
from internal.application.agent_service import AgentService
from internal.application.auth_service import AuthService
from internal.application.resource_service import ResourceService
from internal.application.skill_package_service import SkillPackageService
from internal.application.skill_service import SkillService
from internal.application.tenant_service import TenantService
from internal.domain.entity.resource import Component, Prompt, Tool
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep


def get_auth_service(uow: UowDep) -> AuthService:
    """管理员认证用例。"""
    return AuthService(uow)


def get_agent_service(uow: UowDep, context: RequestContextDep) -> AgentService:
    """智能体用例。"""
    return AgentService(uow, context)


def get_skill_service(uow: UowDep, context: RequestContextDep) -> SkillService:
    """技能用例（含 SKILL.md 同步）。"""
    return SkillService(uow.skills, "技能", uow, context)


def get_skill_package_service(uow: UowDep, context: RequestContextDep) -> SkillPackageService:
    """技能包文件读写、导入导出与克隆用例。"""
    return SkillPackageService(uow, context)


def get_tool_service(uow: UowDep, context: RequestContextDep) -> ResourceService[Tool]:
    """工具用例。"""
    return ResourceService(uow.tools, "工具", uow, context)


def get_component_service(uow: UowDep, context: RequestContextDep) -> ResourceService[Component]:
    """组件用例。"""
    return ResourceService(uow.components, "组件", uow, context)


def get_prompt_service(uow: UowDep, context: RequestContextDep) -> ResourceService[Prompt]:
    """提示词用例。"""
    return ResourceService(uow.prompts, "提示词", uow, context)


def get_admin_user_service(uow: UowDep, context: RequestContextDep) -> AdminUserService:
    """管理员账号管理用例。"""
    return AdminUserService(uow, context)


def get_audit_service(uow: UowDep, context: RequestContextDep) -> AuditService:
    """审计日志查询用例。"""
    return AuditService(uow, context)


def get_tenant_service(uow: UowDep, context: RequestContextDep) -> TenantService:
    """租户管理用例。"""
    return TenantService(uow, context)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]
SkillPackageServiceDep = Annotated[SkillPackageService, Depends(get_skill_package_service)]
ToolServiceDep = Annotated[ResourceService[Tool], Depends(get_tool_service)]
ComponentServiceDep = Annotated[ResourceService[Component], Depends(get_component_service)]
PromptServiceDep = Annotated[ResourceService[Prompt], Depends(get_prompt_service)]
AdminUserServiceDep = Annotated[AdminUserService, Depends(get_admin_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
