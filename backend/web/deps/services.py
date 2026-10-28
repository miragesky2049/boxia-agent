"""应用服务依赖装配：Web 层通过 Depends 获取用例。"""

from typing import Annotated

from fastapi import Depends

from internal.application.admin_user_service import AdminUserService, AuditService
from internal.application.agent_run_service import AgentRunService
from internal.application.agent_service import AgentService
from internal.application.auth_service import AuthService
from internal.application.department_service import DepartmentService
from internal.application.document_service import DocumentService
from internal.application.employment_service import EmploymentService
from internal.application.grant_service import GrantService
from internal.application.hr_dictionary_service import HrDictionaryService
from internal.application.ingestion_service import IngestionService
from internal.application.mcp_sync_service import McpSyncService
from internal.application.mgmt_unit_service import MgmtUnitService
from internal.application.resource_service import ResourceService
from internal.application.retrieval_service import RetrievalService
from internal.application.role_grant_service import RoleGrantService
from internal.application.role_permission_service import RolePermissionService
from internal.application.role_service import RoleService
from internal.application.skill_package_service import SkillPackageService
from internal.application.skill_service import SkillService
from internal.application.tenant_service import TenantService
from internal.application.user_admin_service import UserAdminService
from internal.application.user_auth_service import UserAuthService
from internal.application.user_portal_service import UserPortalService
from internal.application.workflow_run_service import WorkflowRunService
from internal.application.workflow_service import WorkflowService
from internal.domain.entity.resource import Component, Prompt, Tool
from internal.engine.llm import OpenAICompatLLMClient
from internal.engine.query_rewrite import LLMQueryRewriter, QueryRewriter
from internal.engine.rerank import RerankClient, SiliconFlowRerankClient
from internal.infrastructure.config.settings import get_settings
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


def get_department_service(uow: UowDep, context: RequestContextDep) -> DepartmentService:
    """部门管理用例。"""
    return DepartmentService(uow, context)


def get_employment_service(uow: UowDep, context: RequestContextDep) -> EmploymentService:
    """任职记录用例。"""
    return EmploymentService(uow, context)


def get_hr_dictionary_service(uow: UowDep, context: RequestContextDep) -> HrDictionaryService:
    """HR 字典用例。"""
    return HrDictionaryService(uow, context)


def get_mgmt_unit_service(uow: UowDep, context: RequestContextDep) -> MgmtUnitService:
    """管理单元用例。"""
    return MgmtUnitService(uow, context)


def get_grant_service(uow: AdminScopedUowDep, context: RequestContextDep) -> GrantService:
    """资源授权用例。"""
    return GrantService(uow, context)


def get_user_portal_service(uow: UserScopedUowDep, context: RequestContextDep) -> UserPortalService:
    """用户端智能体查询用例。"""
    return UserPortalService(uow, context)


def get_rerank_client() -> RerankClient:
    """Rerank 客户端：SiliconFlow /v1/rerank，复用 embedding 网关凭据。"""
    settings = get_settings()
    return SiliconFlowRerankClient(
        api_key=settings.embedding_api_key.get_secret_value(),
        model=settings.rag_rerank_model,
        base_url=settings.embedding_base_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


def get_query_rewriter() -> QueryRewriter:
    """Query 改写器：复用 LLM 网关（DeepSeek）做指代消解与同义扩展。"""
    settings = get_settings()
    llm = OpenAICompatLLMClient(
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model_id,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return LLMQueryRewriter(llm)


def get_agent_run_service(uow: UserScopedUowDep, context: RequestContextDep) -> AgentRunService:
    """用户端 agent 运行用例：注入 retrieval service（含 rerank + query rewriter）。"""
    settings = get_settings()
    retrieval = RetrievalService(
        uow,
        context,
        rerank_client=get_rerank_client() if settings.rag_rerank_enabled else None,
        query_rewriter=get_query_rewriter() if settings.rag_query_rewrite_enabled else None,
    )
    return AgentRunService(uow, context, retrieval_service=retrieval)


def get_mcp_sync_service(uow: AdminScopedUowDep, context: RequestContextDep) -> McpSyncService:
    """MCP 工具同步用例。"""
    return McpSyncService(uow, context)


def get_document_service(uow: AdminScopedUowDep, context: RequestContextDep) -> DocumentService:
    """知识库文档 CRUD 用例。"""
    return DocumentService(uow, context)


def get_ingestion_service(uow: AdminScopedUowDep, context: RequestContextDep) -> IngestionService:
    """文档 ingest 用例：切分 + embedding + 写 chunks。"""
    return IngestionService(uow, context)


def get_retrieval_service(uow: UserScopedUowDep, context: RequestContextDep) -> RetrievalService:
    """RAG 检索用例：query 改写 → 多 query 召回 → rerank 精排。"""
    settings = get_settings()
    return RetrievalService(
        uow,
        context,
        rerank_client=get_rerank_client() if settings.rag_rerank_enabled else None,
        query_rewriter=get_query_rewriter() if settings.rag_query_rewrite_enabled else None,
    )


def get_workflow_service(
    uow: AdminScopedUowDep, context: RequestContextDep
) -> WorkflowService:
    """工作流与模板用例。"""
    return WorkflowService(uow, context)


def get_workflow_run_service(
    uow: UserScopedUowDep, context: RequestContextDep
) -> WorkflowRunService:
    """用户端工作流运行用例：UoW 已叠加用户可见范围。"""
    return WorkflowRunService(uow, context)


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
DepartmentServiceDep = Annotated[DepartmentService, Depends(get_department_service)]
EmploymentServiceDep = Annotated[EmploymentService, Depends(get_employment_service)]
HrDictionaryServiceDep = Annotated[HrDictionaryService, Depends(get_hr_dictionary_service)]
MgmtUnitServiceDep = Annotated[MgmtUnitService, Depends(get_mgmt_unit_service)]
GrantServiceDep = Annotated[GrantService, Depends(get_grant_service)]
UserPortalServiceDep = Annotated[UserPortalService, Depends(get_user_portal_service)]
AgentRunServiceDep = Annotated[AgentRunService, Depends(get_agent_run_service)]
McpSyncServiceDep = Annotated[McpSyncService, Depends(get_mcp_sync_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]
WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]
WorkflowRunServiceDep = Annotated[WorkflowRunService, Depends(get_workflow_run_service)]

# 类型导出：路由中用于显式标注依赖返回值
__all__ = [
    "AdminUserServiceDep",
    "AgentServiceDep",
    "AuditServiceDep",
    "AuthServiceDep",
    "ComponentServiceDep",
    "UserAdminServiceDep",
    "DepartmentServiceDep",
    "EmploymentServiceDep",
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
    "AgentRunServiceDep",
    "McpSyncServiceDep",
    "DocumentServiceDep",
    "IngestionServiceDep",
    "RetrievalServiceDep",
    "WorkflowServiceDep",
    "WorkflowRunServiceDep",
    "SqlAlchemyUnitOfWork",
]
