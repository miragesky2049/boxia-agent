"""auth hardening：角色、锁定、令牌版本、刷新令牌与审计

Revision ID: 0002_auth_hardening
Revises: 0001_baseline
Create Date: 2026-10-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_auth_hardening"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    "ALTER TABLE admin_users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'admin'",
    "ALTER TABLE admin_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE admin_users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE admin_users ADD COLUMN locked_until TIMESTAMPTZ",
    "ALTER TABLE admin_users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE admin_users ADD COLUMN password_changed_at TIMESTAMPTZ",
    """
    ALTER TABLE admin_users ADD CONSTRAINT ck_admin_users_role
        CHECK (role IN ('superadmin', 'admin', 'viewer'))
    """,
    """
    CREATE TABLE admin_refresh_tokens (
        id              BIGSERIAL PRIMARY KEY,
        user_id         BIGINT       NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
        token_hash      VARCHAR(64)  NOT NULL UNIQUE,
        family_id       UUID         NOT NULL,
        token_version   INTEGER      NOT NULL,
        issued_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
        expires_at      TIMESTAMPTZ  NOT NULL,
        rotated_at      TIMESTAMPTZ,
        revoked_at      TIMESTAMPTZ,
        replaced_by_id  BIGINT,
        ip              VARCHAR(45),
        user_agent      VARCHAR(255)
    )
    """,
    "CREATE INDEX ix_refresh_tokens_user_id    ON admin_refresh_tokens (user_id)",
    "CREATE INDEX ix_refresh_tokens_family_id  ON admin_refresh_tokens (family_id)",
    "CREATE INDEX ix_refresh_tokens_expires_at ON admin_refresh_tokens (expires_at)",
    """
    CREATE TABLE audit_logs (
        id              BIGSERIAL PRIMARY KEY,
        actor_id        BIGINT,
        actor_username  VARCHAR(64)  NOT NULL DEFAULT '',
        action          VARCHAR(64)  NOT NULL,
        resource_type   VARCHAR(64)  NOT NULL DEFAULT '',
        resource_id     VARCHAR(64)  NOT NULL DEFAULT '',
        request_id      VARCHAR(64),
        ip              VARCHAR(45),
        user_agent      VARCHAR(255),
        detail          JSONB        NOT NULL DEFAULT '{}'::jsonb,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at)",
    "CREATE INDEX ix_audit_logs_actor      ON audit_logs (actor_id, created_at)",
    "CREATE INDEX ix_audit_logs_action     ON audit_logs (action, created_at)",
]

_DOWNGRADE = [
    "DROP TABLE IF EXISTS audit_logs",
    "DROP TABLE IF EXISTS admin_refresh_tokens",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_role",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS password_changed_at",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS must_change_password",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS locked_until",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS failed_login_count",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS token_version",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS role",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
