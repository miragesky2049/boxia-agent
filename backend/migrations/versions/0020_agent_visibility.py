"""智能体 user 端可见范围：agents.visibility_mode + 两张关联表。

1) agents 新增 visibility_mode 列（all/custom），默认 all；老数据全部按全员可见处理。
2) 新建 agent_visibility_departments（agent_id, department_id, include_subtree）。
3) 新建 agent_visibility_users（agent_id, user_id）。

Revision ID: 0020_agent_visibility
Revises: 0019_employment_hr_fields
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_agent_visibility"
down_revision: str | None = "0019_employment_hr_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """加列、建关联表与索引。"""
    op.execute(
        "ALTER TABLE agents ADD COLUMN visibility_mode VARCHAR(16) "
        "NOT NULL DEFAULT 'all'"
    )
    op.execute(
        """
        ALTER TABLE agents ADD CONSTRAINT ck_agents_visibility_mode CHECK (
            visibility_mode IN ('all', 'custom'))
        """
    )

    op.execute(
        """
        CREATE TABLE agent_visibility_departments (
            agent_id        UUID        NOT NULL,
            department_id   UUID        NOT NULL,
            include_subtree BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_agent_visibility_departments
                PRIMARY KEY (agent_id, department_id),
            CONSTRAINT fk_avd_agent FOREIGN KEY (agent_id)
                REFERENCES agents (id) ON DELETE CASCADE,
            CONSTRAINT fk_avd_department FOREIGN KEY (department_id)
                REFERENCES departments (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_avd_department ON agent_visibility_departments (department_id)"
    )

    op.execute(
        """
        CREATE TABLE agent_visibility_users (
            agent_id   UUID        NOT NULL,
            user_id    UUID        NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_agent_visibility_users
                PRIMARY KEY (agent_id, user_id),
            CONSTRAINT fk_avu_agent FOREIGN KEY (agent_id)
                REFERENCES agents (id) ON DELETE CASCADE,
            CONSTRAINT fk_avu_user FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_avu_user ON agent_visibility_users (user_id)")


def downgrade() -> None:
    """回滚：删除关联表与新列。"""
    op.execute("DROP TABLE IF EXISTS agent_visibility_users")
    op.execute("DROP TABLE IF EXISTS agent_visibility_departments")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_visibility_mode")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS visibility_mode")
