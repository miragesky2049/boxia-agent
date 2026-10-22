"""search：pg_trgm 扩展与名称/描述模糊检索索引

Revision ID: 0003_search_trgm
Revises: 0002_auth_hardening
Create Date: 2026-10-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003_search_trgm"
down_revision: str | None = "0002_auth_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX ix_agents_name_trgm     ON agents     USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_agents_desc_trgm     ON agents     USING gin (description gin_trgm_ops)",
    "CREATE INDEX ix_skills_name_trgm     ON skills     USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_skills_desc_trgm     ON skills     USING gin (description gin_trgm_ops)",
    "CREATE INDEX ix_tools_name_trgm      ON tools      USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_tools_desc_trgm      ON tools      USING gin (description gin_trgm_ops)",
    "CREATE INDEX ix_components_name_trgm ON components USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_components_desc_trgm ON components USING gin (description gin_trgm_ops)",
    "CREATE INDEX ix_prompts_name_trgm    ON prompts    USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_prompts_desc_trgm    ON prompts    USING gin (description gin_trgm_ops)",
]

_DOWNGRADE = [
    "DROP INDEX IF EXISTS ix_prompts_desc_trgm",
    "DROP INDEX IF EXISTS ix_prompts_name_trgm",
    "DROP INDEX IF EXISTS ix_components_desc_trgm",
    "DROP INDEX IF EXISTS ix_components_name_trgm",
    "DROP INDEX IF EXISTS ix_tools_desc_trgm",
    "DROP INDEX IF EXISTS ix_tools_name_trgm",
    "DROP INDEX IF EXISTS ix_skills_desc_trgm",
    "DROP INDEX IF EXISTS ix_skills_name_trgm",
    "DROP INDEX IF EXISTS ix_agents_desc_trgm",
    "DROP INDEX IF EXISTS ix_agents_name_trgm",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
