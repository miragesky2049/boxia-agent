"""会话与消息：conversation + message。

为 user 端 chat 端点提供多轮对话持久化：
- conversation：一次会话（用户 + 应用维度），首条消息后可生成标题
- message：会话内单条消息（user / assistant / tool / system），assistant 消息可带 tool_calls

Revision ID: 0044_conversation_message
Revises: 0043_drop_legacy_field_version
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_conversation_message"
down_revision: str | None = "0043_drop_legacy_field_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation (
            id             UUID        NOT NULL,
            tenant_id      UUID        NOT NULL,
            user_id        UUID        NOT NULL,
            application_id UUID        NOT NULL,
            title          VARCHAR(200) NOT NULL DEFAULT '',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_conversation PRIMARY KEY (id),
            CONSTRAINT fk_conversation_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_conversation_user FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_conversation_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_conversation_user ON conversation (tenant_id, user_id, updated_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE message (
            id             UUID        NOT NULL,
            conversation_id UUID       NOT NULL,
            tenant_id      UUID        NOT NULL,
            user_id        UUID        NOT NULL,
            application_id UUID        NOT NULL,
            role           VARCHAR(20) NOT NULL,
            content        TEXT        NOT NULL DEFAULT '',
            tool_calls     JSONB,
            tool_call_id   VARCHAR(100),
            tool_name      VARCHAR(100),
            run_id         UUID,
            metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_message PRIMARY KEY (id),
            CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id)
                REFERENCES conversation (id) ON DELETE CASCADE,
            CONSTRAINT fk_message_run FOREIGN KEY (run_id)
                REFERENCES run (id) ON DELETE SET NULL,
            CONSTRAINT ck_message_role CHECK (role IN ('user', 'assistant', 'tool', 'system'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_message_conversation ON message (conversation_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message")
    op.execute("DROP TABLE IF EXISTS conversation")
