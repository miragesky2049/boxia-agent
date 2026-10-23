"""baseline schema（初始表结构基线）

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    """
    CREATE OR REPLACE FUNCTION set_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TABLE admin_users (
        id              BIGSERIAL PRIMARY KEY,
        username        VARCHAR(64)  NOT NULL UNIQUE,
        password_hash   VARCHAR(100) NOT NULL,
        display_name    VARCHAR(64)  NOT NULL DEFAULT '',
        is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
        last_login_at   TIMESTAMPTZ,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE agents (
        id              BIGSERIAL PRIMARY KEY,
        name            VARCHAR(100) NOT NULL,
        avatar_url      VARCHAR(500) NOT NULL DEFAULT '',
        description     TEXT         NOT NULL DEFAULT '',
        config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
        is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_agents_config_object CHECK (jsonb_typeof(config) = 'object')
    )
    """,
    """
    CREATE TABLE skills (
        id              BIGSERIAL PRIMARY KEY,
        name            VARCHAR(100) NOT NULL,
        description     TEXT         NOT NULL DEFAULT '',
        content         TEXT         NOT NULL DEFAULT '',
        config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
        is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_skills_config_object CHECK (jsonb_typeof(config) = 'object')
    )
    """,
    """
    CREATE TABLE tools (
        id              BIGSERIAL PRIMARY KEY,
        name            VARCHAR(100) NOT NULL,
        description     TEXT         NOT NULL DEFAULT '',
        type            VARCHAR(32)  NOT NULL DEFAULT 'http',
        config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
        is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_tools_config_object CHECK (jsonb_typeof(config) = 'object')
    )
    """,
    """
    CREATE TABLE components (
        id              BIGSERIAL PRIMARY KEY,
        name            VARCHAR(100) NOT NULL,
        description     TEXT         NOT NULL DEFAULT '',
        type            VARCHAR(32)  NOT NULL DEFAULT 'card',
        config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
        is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_components_config_object CHECK (jsonb_typeof(config) = 'object')
    )
    """,
    """
    CREATE TABLE prompts (
        id              BIGSERIAL PRIMARY KEY,
        name            VARCHAR(100) NOT NULL,
        description     TEXT         NOT NULL DEFAULT '',
        content         TEXT         NOT NULL DEFAULT '',
        variables       JSONB        NOT NULL DEFAULT '[]'::jsonb,
        category        VARCHAR(32)  NOT NULL DEFAULT '',
        is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_prompts_variables_array CHECK (jsonb_typeof(variables) = 'array')
    )
    """,
    """
    CREATE TABLE agent_tools (
        agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        tool_id  BIGINT NOT NULL REFERENCES tools(id)  ON DELETE CASCADE,
        PRIMARY KEY (agent_id, tool_id)
    )
    """,
    """
    CREATE TABLE agent_skills (
        agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        skill_id BIGINT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
        PRIMARY KEY (agent_id, skill_id)
    )
    """,
    "CREATE UNIQUE INDEX ux_agents_name_lower     ON agents (lower(name))",
    "CREATE UNIQUE INDEX ux_skills_name_lower     ON skills (lower(name))",
    "CREATE UNIQUE INDEX ux_tools_name_lower      ON tools (lower(name))",
    "CREATE UNIQUE INDEX ux_components_name_lower ON components (lower(name))",
    "CREATE UNIQUE INDEX ux_prompts_name_lower    ON prompts (lower(name))",
    "CREATE INDEX ix_agents_updated_at     ON agents (updated_at DESC, id DESC)",
    "CREATE INDEX ix_skills_updated_at     ON skills (updated_at DESC, id DESC)",
    "CREATE INDEX ix_tools_updated_at      ON tools (updated_at DESC, id DESC)",
    "CREATE INDEX ix_components_updated_at ON components (updated_at DESC, id DESC)",
    "CREATE INDEX ix_prompts_updated_at    ON prompts (updated_at DESC, id DESC)",
    "CREATE INDEX ix_agent_tools_tool_id   ON agent_tools (tool_id)",
    "CREATE INDEX ix_agent_skills_skill_id ON agent_skills (skill_id)",
    """
    CREATE TRIGGER trg_admin_users_updated_at BEFORE UPDATE ON admin_users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_agents_updated_at BEFORE UPDATE ON agents
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_skills_updated_at BEFORE UPDATE ON skills
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_tools_updated_at BEFORE UPDATE ON tools
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_components_updated_at BEFORE UPDATE ON components
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_prompts_updated_at BEFORE UPDATE ON prompts
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
]

_DOWNGRADE = [
    "DROP TABLE IF EXISTS agent_skills",
    "DROP TABLE IF EXISTS agent_tools",
    "DROP TABLE IF EXISTS prompts",
    "DROP TABLE IF EXISTS components",
    "DROP TABLE IF EXISTS tools",
    "DROP TABLE IF EXISTS skills",
    "DROP TABLE IF EXISTS agents",
    "DROP TABLE IF EXISTS admin_users",
    "DROP FUNCTION IF EXISTS set_updated_at()",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
