"""智能体 user 端可见范围值对象。"""

from dataclasses import dataclass, field
from uuid import UUID

VISIBILITY_MODE_ALL = "all"
VISIBILITY_MODE_CUSTOM = "custom"
VISIBILITY_MODES = (VISIBILITY_MODE_ALL, VISIBILITY_MODE_CUSTOM)


@dataclass(frozen=True)
class AgentVisibilityDepartment:
    """智能体关联的可见部门（含子树开关）。"""

    department_id: UUID
    include_subtree: bool = True


@dataclass(frozen=True)
class AgentVisibility:
    """智能体 user 端可见范围配置。"""

    mode: str = VISIBILITY_MODE_ALL
    departments: list[AgentVisibilityDepartment] = field(default_factory=list)
    user_ids: list[UUID] = field(default_factory=list)
