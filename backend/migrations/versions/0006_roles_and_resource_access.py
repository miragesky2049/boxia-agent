"""roles & resource access：租户角色、最终用户、资源归属与按角色授权

Revision ID: 0006_roles_and_resource_access
Revises: 0005_skill_files
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_roles_and_resource_access"
down_revision: str | None = "0005_skill_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    # 租户角色：系统角色由租户创建时自动生成，业务角色由租户超管维护
    """
    CREATE TABLE roles (
        id           BIGSERIAL    PRIMARY KEY,
        tenant_id    BIGINT       NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        code         VARCHAR(64)  NOT NULL,
        name         VARCHAR(64)  NOT NULL,
        description  TEXT         NOT NULL DEFAULT '',
        system_role  VARCHAR(16)  NOT NULL,
        is_system    BOOLEAN      NOT NULL DEFAULT FALSE,
        is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ux_roles_tenant_code UNIQUE (tenant_id, code),
        -- 复合外键需要被引用列上有唯一约束
        CONSTRAINT ux_roles_id_tenant UNIQUE (id, tenant_id),
        CONSTRAINT ck_roles_system_role
            CHECK (system_role IN ('superadmin', 'admin', 'viewer'))
    )
    """,
    "CREATE INDEX ix_roles_tenant_active ON roles (tenant_id, is_active)",
    """
    CREATE TRIGGER trg_roles_updated_at BEFORE UPDATE ON roles
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    # 每个存量租户补齐三个系统角色；与 0004 的产品级账号无关
    """
    INSERT INTO roles (tenant_id, code, name, description, system_role, is_system, is_active)
    SELECT t.id, v.code, v.name, v.description, v.code, TRUE, TRUE
      FROM tenants t
     CROSS JOIN (VALUES
            ('superadmin', '超级管理员', '租户最高权限，可管理本租户全部对象与授权'),
            ('admin',      '管理员',     '可读写本租户被授权的业务对象'),
            ('viewer',     '只读成员',   '只读访问被授权的业务对象')
     ) AS v(code, name, description)
    ON CONFLICT (tenant_id, code) DO NOTHING
    """,
    # 最终用户账号：用户端登录身份，绑定租户角色
    """
    CREATE TABLE end_users (
        id                  BIGSERIAL    PRIMARY KEY,
        tenant_id           BIGINT       NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        username            VARCHAR(64)  NOT NULL,
        password_hash       VARCHAR(100) NOT NULL,
        display_name        VARCHAR(64)  NOT NULL DEFAULT '',
        is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
        role_id             BIGINT       NOT NULL,
        token_version       INTEGER      NOT NULL DEFAULT 1,
        failed_login_count  INTEGER      NOT NULL DEFAULT 0,
        locked_until        TIMESTAMPTZ,
        last_login_at       TIMESTAMPTZ,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ux_end_users_tenant_username UNIQUE (tenant_id, username),
        CONSTRAINT fk_end_users_role_tenant
            FOREIGN KEY (role_id, tenant_id)
            REFERENCES roles(id, tenant_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_end_users_tenant_role ON end_users (tenant_id, role_id)",
    """
    CREATE TRIGGER trg_end_users_updated_at BEFORE UPDATE ON end_users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TABLE end_user_refresh_tokens (
        id              BIGSERIAL PRIMARY KEY,
        user_id         BIGINT       NOT NULL REFERENCES end_users(id) ON DELETE CASCADE,
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
    "CREATE INDEX ix_end_user_refresh_tokens_user_id    ON end_user_refresh_tokens (user_id)",
    "CREATE INDEX ix_end_user_refresh_tokens_family_id  ON end_user_refresh_tokens (family_id)",
    "CREATE INDEX ix_end_user_refresh_tokens_expires_at ON end_user_refresh_tokens (expires_at)",
    # 资源授权：role_id 为空表示授予整个租户，非空表示仅授予该租户角色
    """
    CREATE TABLE resource_grants (
        id             BIGSERIAL   PRIMARY KEY,
        resource_type  VARCHAR(16) NOT NULL,
        resource_id    BIGINT      NOT NULL,
        tenant_id      BIGINT      NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        role_id        BIGINT,
        granted_by     BIGINT      REFERENCES admin_users(id) ON DELETE SET NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_resource_grants_type
            CHECK (resource_type IN ('agent', 'skill', 'tool', 'component', 'prompt')),
        CONSTRAINT fk_resource_grants_role_tenant
            FOREIGN KEY (role_id, tenant_id)
            REFERENCES roles(id, tenant_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_resource_grants_resource ON resource_grants (resource_type, resource_id)",
    "CREATE INDEX ix_resource_grants_tenant_role "
    "ON resource_grants (tenant_id, resource_type, role_id)",
    "CREATE UNIQUE INDEX ux_resource_grants_tenant_wide "
    "ON resource_grants (resource_type, resource_id, tenant_id) WHERE role_id IS NULL",
    "CREATE UNIQUE INDEX ux_resource_grants_role "
    "ON resource_grants (resource_type, resource_id, tenant_id, role_id) "
    "WHERE role_id IS NOT NULL",
    # 管理员账号绑定租户角色；role 字符串保留用于系统权限与 JWT 兼容
    "ALTER TABLE admin_users ADD COLUMN role_id BIGINT",
    """
    UPDATE admin_users au
       SET role_id = r.id
      FROM roles r
     WHERE au.tenant_id = r.tenant_id
       AND au.role = r.code
       AND au.tenant_id IS NOT NULL
    """,
    """
    ALTER TABLE admin_users ADD CONSTRAINT ck_admin_users_role_binding
        CHECK (tenant_id IS NULL OR role_id IS NOT NULL)
    """,
    """
    ALTER TABLE admin_users ADD CONSTRAINT fk_admin_users_role_tenant
        FOREIGN KEY (role_id, tenant_id)
        REFERENCES roles(id, tenant_id) ON DELETE RESTRICT
    """,
]

# 资源归属：agent_id 为唯一事实来源，旧关联表仅兼容保留
for _table in ("skills", "tools", "components", "prompts"):
    _UPGRADE += [
        f"ALTER TABLE {_table} ADD COLUMN agent_id BIGINT "
        "REFERENCES agents(id) ON DELETE CASCADE",
        f"CREATE INDEX ix_{_table}_tenant_agent ON {_table} (tenant_id, agent_id)",
    ]

# 仅被单个同租户智能体引用的资源回填归属；多引用保持旧关联，输出在发布说明中
for _table, _relation, _column in (
    ("skills", "agent_skills", "skill_id"),
    ("tools", "agent_tools", "tool_id"),
):
    _UPGRADE.append(
        f"""
        UPDATE {_table} r
           SET agent_id = x.agent_id
          FROM (
                SELECT rel.{_column} AS resource_id, MIN(rel.agent_id) AS agent_id
                  FROM {_relation} rel
                  JOIN {_table} res ON res.id = rel.{_column}
                  JOIN agents ag ON ag.id = rel.agent_id
                 WHERE res.tenant_id IS NOT NULL
                   AND res.tenant_id = ag.tenant_id
                 GROUP BY rel.{_column}
                HAVING COUNT(DISTINCT rel.agent_id) = 1
               ) x
         WHERE r.id = x.resource_id
        """
    )

# 存量产品级智能体与无所属智能体的产品级资源：对全部启用租户保持当前可见性
_UPGRADE += [
    """
    INSERT INTO resource_grants (resource_type, resource_id, tenant_id, role_id)
    SELECT 'agent', a.id, t.id, NULL
      FROM agents a
     CROSS JOIN tenants t
     WHERE a.tenant_id IS NULL
       AND t.is_active
    ON CONFLICT DO NOTHING
    """,
    """
    INSERT INTO resource_grants (resource_type, resource_id, tenant_id, role_id)
    SELECT v.resource_type, v.resource_id, t.id, NULL
      FROM (
            SELECT 'skill' AS resource_type, id AS resource_id
              FROM skills
             WHERE tenant_id IS NULL AND agent_id IS NULL
            UNION ALL
            SELECT 'tool', id FROM tools
             WHERE tenant_id IS NULL AND agent_id IS NULL
            UNION ALL
            SELECT 'component', id FROM components
             WHERE tenant_id IS NULL AND agent_id IS NULL
            UNION ALL
            SELECT 'prompt', id FROM prompts
             WHERE tenant_id IS NULL AND agent_id IS NULL
           ) v
     CROSS JOIN tenants t
     WHERE t.is_active
    ON CONFLICT DO NOTHING
    """,
]

_DOWNGRADE = [
    "DROP INDEX IF EXISTS ix_skills_tenant_agent",
    "DROP INDEX IF EXISTS ix_tools_tenant_agent",
    "DROP INDEX IF EXISTS ix_components_tenant_agent",
    "DROP INDEX IF EXISTS ix_prompts_tenant_agent",
    "ALTER TABLE skills DROP COLUMN IF EXISTS agent_id",
    "ALTER TABLE tools DROP COLUMN IF EXISTS agent_id",
    "ALTER TABLE components DROP COLUMN IF EXISTS agent_id",
    "ALTER TABLE prompts DROP COLUMN IF EXISTS agent_id",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS fk_admin_users_role_tenant",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_role_binding",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS role_id",
    "DROP TABLE IF EXISTS resource_grants",
    "DROP TABLE IF EXISTS end_user_refresh_tokens",
    "DROP TRIGGER IF EXISTS trg_end_users_updated_at ON end_users",
    "DROP TABLE IF EXISTS end_users",
    "DROP TRIGGER IF EXISTS trg_roles_updated_at ON roles",
    "DROP TABLE IF EXISTS roles",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
