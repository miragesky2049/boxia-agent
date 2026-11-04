"""用户管理解除主角色必填：角色授权统一由「用户授权」维护。

Revision ID: 0065_users_role_optional
Revises: 0064_app_delete_permission
Create Date: 2026-11-04

背景：
- 用户管理表单不再承担权限配置，创建用户时可以不指定角色，后续在「用户授权」页面分配。
- users.role_id 仅作为主角色展示/兼容用途，允许为空；实际授权以 user_roles 关联表为准。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065_users_role_optional"
down_revision: str | None = "0064_app_delete_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role_id DROP NOT NULL")


def downgrade() -> None:
    raise NotImplementedError("已允许无角色用户，无法安全回滚 role_id NOT NULL 约束")
