"""行级数据权限 SQL 片段：按当前调用者被授权的管理单元展开后的部门/人员集合过滤租户智能体。

过滤规则：
- snapshot 为 None：不叠加行过滤（平台账号或拥有 system:data:all）
- snapshot 为空（未被授权任何管理单元）：fail-closed，仅本人创建的智能体可见
- 否则：department_id 命中展开后的部门集合 OR created_by 命中展开后的人员集合
"""

from typing import Any
from uuid import UUID

from sqlalchemy import false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.entity.data_scope import UserDataScope
from internal.infrastructure.model.agent import AgentModel


def agent_row_filter(scope: UserDataScope) -> ColumnElement[bool]:
    """把用户数据范围编译为 agents 行过滤条件（仅作用于租户智能体）。"""
    if scope.is_empty:
        return AgentModel.created_by == scope.user_id

    parts: list[ColumnElement[bool]] = []
    if scope.visible_department_ids:
        parts.append(AgentModel.department_id.in_(list(scope.visible_department_ids)))
    if scope.visible_user_ids:
        parts.append(AgentModel.created_by.in_(list(scope.visible_user_ids)))
    if not parts:
        return false()
    return or_(*parts)


__all__ = ["agent_row_filter"]
