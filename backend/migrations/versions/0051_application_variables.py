"""0051 变量体系：应用变量定义 + 用户变量取值。

Revision ID: 0051_application_variables
Revises: 0050_conversation_channel
Create Date: 2026-11-02

设计要点：
- application.variables 存应用变量/用户变量的定义（name/type/default/scope）
- application_user_variable 存用户变量的实际取值，按 application + user + key 唯一
- 不引入 conversation.variables，避免与用户变量语义重叠
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_application_variables"
down_revision: str | None = "0050_conversation_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application",
        sa.Column(
            "variables",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="变量定义：name/type/default/scope(app|user)",
        ),
    )
    op.create_check_constraint(
        "ck_application_variables_array",
        "application",
        "jsonb_typeof(variables) = 'array'",
    )

    op.execute(
        """
        CREATE TABLE application_user_variable (
            id             UUID        NOT NULL,
            application_id UUID        NOT NULL,
            user_id        UUID        NOT NULL,
            variable_key   VARCHAR(128) NOT NULL,
            value          JSONB       NOT NULL DEFAULT 'null'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_application_user_variable PRIMARY KEY (id),
            CONSTRAINT uq_application_user_variable UNIQUE (application_id, user_id, variable_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_application_user_variable_app_user
        ON application_user_variable (application_id, user_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_application_user_variable_app_user")
    op.execute("DROP TABLE IF EXISTS application_user_variable")
    op.drop_constraint("ck_application_variables_array", "application", type_="check")
    op.drop_column("application", "variables")
