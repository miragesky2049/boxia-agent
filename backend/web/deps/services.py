"""应用服务依赖装配：Web 层通过 Depends 获取用例。"""

from typing import Annotated

from fastapi import Depends

from internal.application.admin_user_service import AdminUserService, AuditService
from internal.application.agent_service import AgentService
from internal.application.auth_service import AuthService
from internal.application.resource_service import ResourceService
from internal.domain.entity.resource import Component, Prompt, Skill, Tool
from web.deps.db import UowDep


def get_auth_service(uow: UowDep) -> AuthService:
    """管理员认证用例。"""
    return AuthService(uow)


def get_agent_service(uow: UowDep) -> AgentService:
    """智能体用例。"""
    return AgentService(uow)


def get_skill_service(uow: UowDep) -> ResourceService[Skill]:
    """技能用例。"""
    return ResourceService(uow.skills, "技能", uow)


def get_tool_service(uow: UowDep) -> ResourceService[Tool]:
    """工具用例。"""
    return ResourceService(uow.tools, "工具", uow)


def get_component_service(uow: UowDep) -> ResourceService[Component]:
    """组件用例。"""
    return ResourceService(uow.components, "组件", uow)


def get_prompt_service(uow: UowDep) -> ResourceService[Prompt]:
    """提示词用例。"""
    return ResourceService(uow.prompts, "提示词", uow)


def get_admin_user_service(uow: UowDep) -> AdminUserService:
    """管理员账号管理用例。"""
    return AdminUserService(uow)


def get_audit_service(uow: UowDep) -> AuditService:
    """审计日志查询用例。"""
    return AuditService(uow)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
SkillServiceDep = Annotated[ResourceService[Skill], Depends(get_skill_service)]
ToolServiceDep = Annotated[ResourceService[Tool], Depends(get_tool_service)]
ComponentServiceDep = Annotated[ResourceService[Component], Depends(get_component_service)]
PromptServiceDep = Annotated[ResourceService[Prompt], Depends(get_prompt_service)]
AdminUserServiceDep = Annotated[AdminUserService, Depends(get_admin_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
