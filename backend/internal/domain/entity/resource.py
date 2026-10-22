"""技能、工具、组件、提示词领域实体。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Skill:
    """技能。"""

    id: int
    name: str
    description: str
    content: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源（所有租户可见、仅产品级平台可维护）。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Tool:
    """工具。"""

    id: int
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Component:
    """组件。"""

    id: int
    name: str
    description: str
    type: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Prompt:
    """提示词。"""

    id: int
    name: str
    description: str
    content: str
    variables: list[str]
    category: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级资源。"""
        return self.tenant_id is None


@dataclass(frozen=True)
class Agent:
    """智能体。"""

    id: int
    name: str
    avatar_url: str
    description: str
    config: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    tool_ids: list[int] = field(default_factory=list)
    skill_ids: list[int] = field(default_factory=list)
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级智能体。"""
        return self.tenant_id is None
