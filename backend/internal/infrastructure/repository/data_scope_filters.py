"""行级数据权限 SQL 片段：按当前调用者被授权的管理单元展开后的部门/人员集合过滤租户智能体。

过滤规则：
- snapshot 为 None：不叠加行过滤（平台账号或拥有 system:data:all）
- 平台智能体（tenant_id=PLATFORM_TENANT_ID）不受行级数据范围约束，由角色授权/开通收敛
- snapshot 为空（未被授权任何管理单元）：fail-closed，仅本人创建的租户智能体可见
- 否则：department_id 命中展开后的部门集合 OR created_by 命中展开后的人员集合
"""

from typing import Any
from uuid import UUID

from sqlalchemy import false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.data_scope import UserDataScope
from internal.infrastructure.model.agent import AgentModel


def agent_row_filter(scope: UserDataScope) -> ColumnElement[bool]:
    """把用户数据范围编译为 agents 行过滤条件（仅作用于租户智能体；平台智能体豁免）。"""
    tenant_owned_branch: ColumnElement[bool]
    if scope.is_empty:
        tenant_owned_branch = AgentModel.created_by == scope.user_id
    else:
        parts: list[ColumnElement[bool]] = []
        if scope.visible_department_ids:
            parts.append(AgentModel.department_id.in_(list(scope.visible_department_ids)))
        if scope.visible_user_ids:
            parts.append(AgentModel.created_by.in_(list(scope.visible_user_ids)))
        if not parts:
            tenant_owned_branch = false()
        else:
            tenant_owned_branch = or_(*parts)
    return or_(
        AgentModel.tenant_id == PLATFORM_TENANT_ID,
        tenant_owned_branch,
    )


__all__ = ["agent_row_filter"]
