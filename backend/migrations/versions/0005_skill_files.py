"""skill packages：技能包内文件表，平台级与租户级按 skills.tenant_id 隔离

Revision ID: 0005_skill_files
Revises: 0004_multi_tenant
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_skill_files"
down_revision: str | None = "0004_multi_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    """
    CREATE TABLE skill_files (
        id            BIGSERIAL    PRIMARY KEY,
        skill_id      BIGINT       NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
        path          VARCHAR(512) NOT NULL,
        content       TEXT         NOT NULL DEFAULT '',
        content_hash  CHAR(64)     NOT NULL,
        size_bytes    INTEGER      NOT NULL,
        media_type    VARCHAR(100) NOT NULL DEFAULT 'text/plain',
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ux_skill_files_path UNIQUE (skill_id, path),
        CONSTRAINT ck_skill_files_path CHECK (
            path <> ''
            AND left(path, 1) <> '/'
            AND strpos(path, chr(92)) = 0
            AND path !~ '(^|/)[.][.]?(/|$)'
            AND path !~ '[[:cntrl:]]'
        ),
        CONSTRAINT ck_skill_files_size CHECK (size_bytes >= 0)
    )
    """,
    "CREATE INDEX ix_skill_files_skill ON skill_files (skill_id, path)",
    """
    CREATE TRIGGER trg_skill_files_updated_at BEFORE UPDATE ON skill_files
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    # 存量单文件技能回填为 SKILL.md
    """
    INSERT INTO skill_files (skill_id, path, content, content_hash, size_bytes, media_type)
    SELECT id,
           'SKILL.md',
           content,
           encode(sha256(convert_to(content, 'UTF8')), 'hex'),
           octet_length(convert_to(content, 'UTF8')),
           'text/markdown'
      FROM skills
     WHERE content <> ''
    ON CONFLICT (skill_id, path) DO NOTHING
    """,
    # 早期导入把 references/documents 存在 config JSONB 中，迁移为真实目录文件
    """
    INSERT INTO skill_files (skill_id, path, content, content_hash, size_bytes, media_type)
    SELECT s.id,
           kv.key,
           kv.value,
           encode(sha256(convert_to(kv.value, 'UTF8')), 'hex'),
           octet_length(convert_to(kv.value, 'UTF8')),
           CASE WHEN kv.key LIKE '%.md' THEN 'text/markdown' ELSE 'text/plain' END
      FROM skills s
      CROSS JOIN LATERAL jsonb_each_text(s.config -> 'references') AS kv(key, value)
     WHERE jsonb_typeof(s.config -> 'references') = 'object'
       AND kv.key <> ''
       AND left(kv.key, 1) <> '/'
       AND strpos(kv.key, chr(92)) = 0
       AND kv.key !~ '(^|/)[.][.]?(/|$)'
       AND kv.key !~ '[[:cntrl:]]'
    ON CONFLICT (skill_id, path) DO NOTHING
    """,
    """
    INSERT INTO skill_files (skill_id, path, content, content_hash, size_bytes, media_type)
    SELECT s.id,
           kv.key,
           kv.value,
           encode(sha256(convert_to(kv.value, 'UTF8')), 'hex'),
           octet_length(convert_to(kv.value, 'UTF8')),
           CASE WHEN kv.key LIKE '%.md' THEN 'text/markdown' ELSE 'text/plain' END
      FROM skills s
      CROSS JOIN LATERAL jsonb_each_text(s.config -> 'documents') AS kv(key, value)
     WHERE jsonb_typeof(s.config -> 'documents') = 'object'
       AND kv.key <> ''
       AND left(kv.key, 1) <> '/'
       AND strpos(kv.key, chr(92)) = 0
       AND kv.key !~ '(^|/)[.][.]?(/|$)'
       AND kv.key !~ '[[:cntrl:]]'
    ON CONFLICT (skill_id, path) DO NOTHING
    """,
    # config 只保留元数据，文件内容以 skill_files 为唯一来源
    """
    UPDATE skills
       SET config = config - 'references' - 'documents'
     WHERE config ? 'references' OR config ? 'documents'
    """,
]

_DOWNGRADE = [
    "DROP TRIGGER IF EXISTS trg_skill_files_updated_at ON skill_files",
    "DROP TABLE IF EXISTS skill_files",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
