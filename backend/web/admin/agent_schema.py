"""智能体配置的请求/响应模型，与 agents.config JSONB 结构一一对应。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FaqItem(BaseModel):
    """常见问题条目。"""

    question: str = Field(default="", max_length=500)
    answer: str = Field(default="", max_length=2000)


class ModelSettings(BaseModel):
    """模型配置。"""

    model: str = "glm-5"
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=1, le=200000)
    reasoning_effort: str = "medium"
    context_window: int = Field(default=65536, ge=1, le=2000000)
    max_thinking_tokens: int = Field(default=2000, ge=0, le=200000)


class PromptSettings(BaseModel):
    """提示词配置。"""

    role_setting: str = Field(default="", max_length=50000)
    persona: str = Field(default="", max_length=20000)
    user_prompt: str = Field(default="", max_length=20000)
    memory_count: int = Field(default=20, ge=0, le=200)
    memory_model: str = "glm-5"


class MemorySettings(BaseModel):
    """记忆配置。"""

    enabled: bool = False
    task_memory_prompt: str = Field(default="", max_length=10000)
    long_term_enabled: bool = False
    long_term_prompt: str = Field(default="", max_length=10000)


class ConversationSettings(BaseModel):
    """对话设置。"""

    welcome: str = Field(default="", max_length=2000)
    fallback: str = Field(default="", max_length=2000)
    input_placeholder: str = Field(default="", max_length=200)
    common_questions_enabled: bool = False
    faqs: list[FaqItem] = Field(default_factory=list)


class ChannelSettings(BaseModel):
    """渠道设置。"""

    type: str = "web"
    enabled: bool = True


class KnowledgeSettings(BaseModel):
    """知识库设置。"""

    enabled: bool = False
    dataset_ids: list[str] = Field(default_factory=list)


class OtherSettings(BaseModel):
    """其他配置。"""

    system_prompt_template: str = "default"
    max_turns: int = Field(default=30, ge=1, le=500)
    deep_thinking: bool = True
    show_reasoning: bool = True
    web_search: bool = False
    create_task: bool = True
    history_task: bool = True
    scheduled_task: bool = False
    artifacts: bool = False
    upload_attachment: bool = True
    upload_file_types: list[str] = Field(
        default_factory=lambda: [
            "txt",
            "md",
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "csv",
            "ppt",
            "pptx",
        ]
    )
    upload_max_size_mb: int = Field(default=10, ge=1, le=100)
    task_list: bool = False


class AgentConfig(BaseModel):
    """智能体完整配置。"""

    model: ModelSettings = Field(default_factory=ModelSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    channel: ChannelSettings = Field(default_factory=ChannelSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    other: OtherSettings = Field(default_factory=OtherSettings)
    extensions: dict[str, int | None] = Field(default_factory=dict)


class AgentPayload(BaseModel):
    """智能体入参。"""

    name: str = Field(min_length=1, max_length=100)
    avatar_url: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=5000)
    is_enabled: bool = True
    config: AgentConfig = Field(default_factory=AgentConfig)
    tool_ids: list[int] = Field(default_factory=list)
    skill_ids: list[int] = Field(default_factory=list)


class AgentSummaryOut(BaseModel):
    """智能体列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_url: str
    description: str
    is_enabled: bool
    tenant_id: int | None = None
    is_platform: bool = False
    created_at: datetime
    updated_at: datetime


class AgentOut(AgentSummaryOut):
    """智能体详情。"""

    config: AgentConfig
    tool_ids: list[int] = Field(default_factory=list)
    skill_ids: list[int] = Field(default_factory=list)
