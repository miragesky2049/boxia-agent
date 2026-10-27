"""user 端智能体可见范围 SQL 片段：按智能体实例配置的可见部门/人员过滤。

与 admin 端 `data_scope_filters.agent_row_filter`（以用户为中心的管理单元行级权限）
不同，本模块是以智能体为中心的实例级 ACL：
- agents.visibility_mode = 'all'：全员可见，直接放行。
- agents.visibility_mode = 'custom'：当前用户命中任一规则即可见：
  1) 当前用户 id 直接出现在 agent_visibility_users；
  2) 当前用户的当前任职部门命中某条 agent_visibility_departments 规则：
     - 精确命中：规则部门 id = 当前部门 id（无论是否含子树）；
     - 子树命中：include_subtree=true 且当前部门 path 以规则部门 path 为前缀。
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, func, literal, or_
from sqlalchemy.sql.elements import ColumnElement

from internal.infrastructure.model.agent import (
    AgentModel,
    AgentVisibilityDepartmentModel,
    AgentVisibilityUserModel,
)
from internal.infrastructure.model.department import DepartmentModel


@dataclass(frozen=True)
class UserAgentVisibilityContext:
    """当前 user 端调用者用于智能体实例级可见过滤的快照。

    current_department_id / current_department_path 来自当前任职（is_current=True）；
    用户无当前任职时两者均为 None，此时仅命中 all 模式与直接指定的 user_id 规则。
    """

    current_user_id: UUID
    current_department_id: UUID | None = None
    current_department_path: str | None = None


def agent_user_visible_filter(
    current_user_id: UUID,
    current_department_id: UUID | None,
    current_department_path: str | None,
) -> ColumnElement[bool]:
    """把当前 user 端用户编译为 agents 行过滤条件（仅作用于租户智能体）。"""
    parts: list[ColumnElement[bool]] = [
        AgentModel.visibility_mode == "all",
        exists().where(
            (AgentVisibilityUserModel.agent_id == AgentModel.id)
            & (AgentVisibilityUserModel.user_id == current_user_id)
        ),
    ]

    if current_department_id is not None:
        # 精确命中：当前部门被直接关联（无论 include_subtree 开关）
        parts.append(
            exists().where(
                (AgentVisibilityDepartmentModel.agent_id == AgentModel.id)
                & (
                    AgentVisibilityDepartmentModel.department_id
                    == current_department_id
                )
            )
        )

    if current_department_path:
        # 子树命中：当前部门位于某条"含子树"规则的部门子树内
        parts.append(
            exists()
            .where(
                (AgentVisibilityDepartmentModel.agent_id == AgentModel.id)
                & (AgentVisibilityDepartmentModel.include_subtree.is_(True))
                & (
                    DepartmentModel.id
                    == AgentVisibilityDepartmentModel.department_id
                )
                & literal(current_department_path).like(
                    func.concat(DepartmentModel.path, "%")
                )
            )
        )

    return or_(*parts)


__all__ = ["agent_user_visible_filter"]
