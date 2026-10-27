"""技能、工具、组件、提示词领域实体。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Skill:
    """技能。"""

    id: UUID
    name: str
    description: str
    content: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None
    agent_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源（所有租户可见、仅产品级平台可维护）。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class SkillFile:
    """技能包内的单个文件，path 为技能包根目录下的相对路径。"""

    id: UUID
    skill_id: UUID
    path: str
    content: str
    content_hash: str
    size_bytes: int
    media_type: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Tool:
    """工具。"""

    id: UUID
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None
    agent_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Component:
    """组件。"""

    id: UUID
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None
    agent_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Prompt:
    """提示词。"""

    id: UUID
    name: str
    description: str
    content: str
    variables: list[str]
    category: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None
    agent_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Agent:
    """智能体。"""

    id: UUID
    name: str
    avatar_url: str
    description: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tool_ids: list[UUID] = field(default_factory=list)
    skill_ids: list[UUID] = field(default_factory=list)
    tenant_id: UUID | None = None
    department_id: UUID | None = None
    # 创建者（租户管理员 users.id），行级数据权限"本人创建"过滤依赖该列
    created_by: UUID | None = None
    # user 端可见范围：all=全员可见；custom=按 agent_visibility_* 关联表过滤
    visibility_mode: str = "all"

    @property
    def is_platform(self) -> bool:
        """是否为产品级智能体。"""
        return self.tenant_id is None
