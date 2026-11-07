"""平台应用管理（apps-admin）请求模型。"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AppCreatePayload(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=2000)
    # workflow（工作流） / chatflow（对话流） / agent（智能体，0074）
    flow_type: str = Field("workflow", pattern="^(workflow|chatflow|agent)$")
    # 0068 可见范围 v2：产品级应用的平台侧默认值
    visibility_template: Literal["all", "whitelist"] = "all"
    visibility_lock: bool = False


class AppUpdatePayload(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=500)
    flow_type: str | None = Field(None, pattern="^(workflow|chatflow|agent)$")
    # 0068 可见范围 v2：仅产品级应用可设置（owner_type 校验在 service 层）
    visibility_template: Literal["all", "whitelist"] | None = None
    visibility_lock: bool | None = None
    admin_scope_mode: Literal["creator_only", "mgmt_unit", "all_admin"] | None = None


class GraphPayload(BaseModel):
    graph: dict[str, Any]
    changelog: str = ""


class AgentConfigPayload(BaseModel):
    """0074 智能体配置表单请求体。

    键名与画布配置面保持 camelCase（coze 口径）；本模型只做结构承载与
    OpenAPI 文档，业务校验（必填/上限/保留前缀）在 domain/canvas/agent_config。
    """

    systemPrompt: str = ""
    modleName: str = ""
    maxToolRounds: int | None = None
    openingRemarks: str = ""
    suggestedQuestions: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    mcpServers: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    memory: dict[str, Any] = Field(default_factory=dict)
    reasoningMode: str = "react"
    plannerPrompt: str | None = None
    reflectorPrompt: str | None = None
    maxReflectRounds: int | None = None
    sensitiveTools: list[dict[str, Any]] = Field(default_factory=list)
    # 0074 PRD F9（M3）：视觉开关（前端按所选模型 capabilities.supports_vision 门控）
    visionEnabled: bool = False
    tokenBudget: int | None = None


class ListingPayload(BaseModel):
    listed: bool


class EnabledPayload(BaseModel):
    enabled: bool


class ValidateGraphPayload(BaseModel):
    """试运行前的结构校验请求体。"""

    graph: dict[str, Any]
    application_id: UUID | None = None


class VariablesPayload(BaseModel):
    variables: list[dict[str, Any]] = Field(default_factory=list)


class UserVariablesPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class RollbackGraphPayload(BaseModel):
    version: int


class TenantConfigPayload(BaseModel):
    tenant_id: UUID
    config_key: str
    config_value: Any


class PinGraphVersionPayload(BaseModel):
    tenant_id: UUID
    version: int | None = None


class DebugRunPayload(BaseModel):
    graph: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    # 对话流会话上下文：消息类节点回退使用；不传则由「创建会话」节点产出
    conversation_id: UUID | None = None
    # 多轮试运行时复用同一个 thread，保证 checkpoint / 历史消息连续
    thread_id: str | None = None
    # 真实应用 ID：对话流试运行会把消息落到该应用下（channel=debug）
    application_id: UUID | None = None


class DebugNodeRunPayload(BaseModel):
    """单节点试运行请求体。"""

    graph: dict[str, Any]
    node_id: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    conversation_id: UUID | None = None


class DebugConversationPayload(BaseModel):
    """画布对话流试运行：创建一个 debug 会话。"""

    application_id: UUID
    title: str = Field("画布试运行", max_length=200)


class DebugResumePayload(BaseModel):
    """人审 / 问答续跑请求体。"""

    graph: dict[str, Any]
    thread_id: str
    run_id: str | None = None
    conversation_id: UUID | None = None
    application_id: UUID | None = None
    # 人审批复：{"approved": bool, "comment": str, "approver": str}
    approval: dict[str, Any] | None = None
    # 问答节点回答等自由载荷：{"answer": "..."}
    resume: dict[str, Any] | None = None


class AppDeleteOut(BaseModel):
    """单应用删除结果。"""

    application_id: UUID
    name: str
    audit_id: UUID
    deleted: dict[str, int] = Field(default_factory=dict)


class AppBatchDeleteRequest(BaseModel):
    """批量删除应用请求；confirm 必须显式传 true。"""

    application_ids: list[UUID] = Field(min_length=1, max_length=100)
    confirm: bool = False
    reason: str = Field(default="", max_length=200)


class AppBatchDeleteItemOut(BaseModel):
    """批量删除单项结果。"""

    application_id: UUID
    name: str | None = None
    success: bool
    audit_id: UUID | None = None
    error_code: str | None = None
    error: str | None = None


class AppBatchDeleteOut(BaseModel):
    """批量删除汇总结果（部分成功时 HTTP 仍为 200）。"""

    total: int
    succeeded: int
    failed: int
    items: list[AppBatchDeleteItemOut]


class AppCopyOut(BaseModel):
    """复制应用结果。"""

    application_id: UUID
    name: str
    source_application_id: UUID
