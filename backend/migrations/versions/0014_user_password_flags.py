"""users 增加首登改密标记与改密时间。

租户管理员并入 users 后缺失首登强制改密状态，导致改密后无法清除标记。
存量账号保持不需要改密，只有新建或重置密码的账号才会被置为需要改密。

Revision ID: 0014_user_password_flags
Revises: 0013_uuid_primary_keys
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_user_password_flags"
down_revision: str | None = "0013_uuid_primary_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMPTZ",
]

_DOWNGRADE = [
    "ALTER TABLE users DROP COLUMN IF EXISTS password_changed_at",
    "ALTER TABLE users DROP COLUMN IF EXISTS must_change_password",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
