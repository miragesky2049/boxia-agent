"""用户员工字段：在 users 表新增 HR 基础信息列。

新增字段：工号、手机号、邮箱、性别、出生日期、头像、备注。

Revision ID: 0018_user_hr_fields
Revises: 0017_mgmt_unit_rebindings
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_user_hr_fields"
down_revision: str | None = "0017_mgmt_unit_rebindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 users 表追加 HR 字段。"""
    op.execute("ALTER TABLE users ADD COLUMN employee_no VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(32)")
    op.execute("ALTER TABLE users ADD COLUMN email VARCHAR(128)")
    op.execute("ALTER TABLE users ADD COLUMN gender VARCHAR(16)")
    op.execute("ALTER TABLE users ADD COLUMN birth_date DATE")
    op.execute("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE users ADD COLUMN remark TEXT NOT NULL DEFAULT ''")

    # 同租户内工号唯一（NULL 不参与唯一索引）
    op.execute(
        """
        CREATE UNIQUE INDEX ux_users_tenant_employee_no
            ON users (tenant_id, employee_no)
            WHERE employee_no IS NOT NULL
        """
    )


def downgrade() -> None:
    """回滚：删除新增列。"""
    op.execute("DROP INDEX IF EXISTS ux_users_tenant_employee_no")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS remark")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS birth_date")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS gender")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS phone")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS employee_no")
