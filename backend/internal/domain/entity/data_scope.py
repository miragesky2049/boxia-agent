"""行级数据范围快照：由用户被授权的管理单元展开而来，供智能体行过滤使用。"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UserDataScope:
    """当前调用者的行级数据范围。

    visible_department_ids: 由已授权管理单元的"关联部门（含子树）"展开得到的部门 id 集合。
    visible_user_ids: 由已授权管理单元的"关联人员"展开得到的用户 id 集合。
    智能体可见条件：department_id 命中集合 OR created_by 命中集合。
    """

    tenant_id: UUID
    user_id: UUID
    visible_department_ids: frozenset[UUID] = frozenset()
    visible_user_ids: frozenset[UUID] = frozenset()

    @property
    def is_empty(self) -> bool:
        """未被授权任何管理单元：fail-closed，仅本人创建的智能体可见。"""
        return not self.visible_department_ids and not self.visible_user_ids
