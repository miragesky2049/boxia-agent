"""应用可见范围：application_visibility_departments + application_visibility_users。

对应老规则（0020_agent_visibility），但指向 application 表。
- visibility_mode='all' 时两张表为空，全员可见；
- visibility_mode='custom' 时按部门（含子树开关）+ 用户白名单收敛。

Revision ID: 0039_app_visibility
Revises: 0038_apps_menu_permissions
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039_app_visibility"
down_revision: str | None = "0038_apps_menu_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE application_visibility_departments (
            application_id  UUID        NOT NULL,
            department_id   UUID        NOT NULL,
            include_subtree BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_application_visibility_departments
                PRIMARY KEY (application_id, department_id),
            CONSTRAINT fk_avd_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE,
            CONSTRAINT fk_avd_department FOREIGN KEY (department_id)
                REFERENCES departments (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_avd_department ON application_visibility_departments (department_id)"
    )

    op.execute(
        """
        CREATE TABLE application_visibility_users (
            application_id UUID        NOT NULL,
            user_id        UUID        NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_application_visibility_users
                PRIMARY KEY (application_id, user_id),
            CONSTRAINT fk_avu_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE,
            CONSTRAINT fk_avu_user FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_avu_user ON application_visibility_users (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS application_visibility_users")
    op.execute("DROP TABLE IF EXISTS application_visibility_departments")
