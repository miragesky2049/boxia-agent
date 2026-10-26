"""移除 user_mgmt_unit_grants.granted_by 对 admin_users 的外键约束。

授权人既可能是平台管理员（admin_users），也可能是租户账号（users），
无法用单一外键约束引用；与 resource_grants / role_permissions 的
granted_by 处理保持一致。该约束导致租户管理员保存用户授权时报
"数据冲突，请检查名称等唯一字段"（实际为外键冲突）。

Revision ID: 0021_drop_umug_granted_by_fk
Revises: 0020_agent_visibility
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_drop_umug_granted_by_fk"
down_revision: str | None = "0020_agent_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """删除 granted_by 对 admin_users 的外键约束。"""
    op.execute(
        "ALTER TABLE user_mgmt_unit_grants "
        "DROP CONSTRAINT IF EXISTS fk_umug_granted_by"
    )


def downgrade() -> None:
    """回滚：恢复外键约束（历史租户授权数据需先清理，否则可能失败）。"""
    op.execute(
        "ALTER TABLE user_mgmt_unit_grants "
        "ADD CONSTRAINT fk_umug_granted_by FOREIGN KEY (granted_by) "
        "REFERENCES admin_users (id) ON DELETE SET NULL"
    )
