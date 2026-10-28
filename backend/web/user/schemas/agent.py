"""用户端智能体与资源响应模型。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserSkillOut(BaseModel):
    """用户端技能。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    content: str
    config: dict[str, Any]
    is_enabled: bool


class UserToolOut(BaseModel):
    """用户端工具。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool


class UserComponentOut(UserToolOut):
    """用户端组件。"""


class UserPromptOut(BaseModel):
    """用户端提示词。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    content: str
    variables: list[str]
    category: str
    is_enabled: bool


class UserAgentSummaryOut(BaseModel):
    """用户端智能体列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    avatar_url: str
    description: str
    is_enabled: bool


class UserAgentDetailOut(UserAgentSummaryOut):
    """用户端智能体详情：仅包含已授权且启用的资源。"""

    config: dict[str, Any]
    skills: list[UserSkillOut]
    tools: list[UserToolOut]
    components: list[UserComponentOut]
    prompts: list[UserPromptOut]
