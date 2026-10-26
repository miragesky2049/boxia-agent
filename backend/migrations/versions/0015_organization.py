"""组织架构：部门（物化路径，最多10级）、用户任职（单一主任职）、智能体归属部门。

部门表与任职表带完整租户隔离约束，并以复合外键防止跨租户引用；
新增组织架构权限码并回填存量租户系统角色。部门删除受外键与应用层双重保护，
有子部门/任职/归属智能体时禁止物理删除。

Revision ID: 0015_organization
Revises: 0014_user_password_flags
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_organization"
down_revision: str | None = "0014_user_password_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 永不会被应用层 UUID v7 分配的 nil UUID，用于在唯一索引中占位 NULL 父部门。
_NIL_UUID = "00000000-0000-0000-0000-000000000000"

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:departments", "部门管理", "menu", "view", 45, ""),
    ("menu:employments", "任职管理", "menu", "view", 46, ""),
    ("page:departments", "部门管理页面", "page", "view", 145, ""),
    ("page:employments", "任职管理页面", "page", "view", 146, ""),
    ("button:department:create", "部门-新建", "button", "create", 360, ""),
    ("button:department:update", "部门-编辑", "button", "update", 361, ""),
    ("button:department:delete", "部门-删除", "button", "delete", 362, ""),
    ("button:employment:create", "任职-新建", "button", "create", 370, ""),
    ("button:employment:update", "任职-编辑/调岗/结束任职", "button", "update", 371, ""),
    ("button:employment:delete", "任职-删除", "button", "delete", 372, ""),
)

# 组织架构仅租户侧可用，平台系统角色不授予。
_READ_CODES = (
    "menu:departments",
    "menu:employments",
    "page:departments",
    "page:employments",
)
_WRITE_CODES = (
    "button:department:create",
    "button:department:update",
    "button:department:delete",
    "button:employment:create",
    "button:employment:update",
    "button:employment:delete",
)
_ALL_CODES = (*_READ_CODES, *_WRITE_CODES)


def _permission_values() -> str:
    """构造权限目录批量插入的 VALUES 子句。"""
    return ",\n        ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: tuple[str, ...]) -> str:
    """把权限码元组渲染为 PostgreSQL 字符串数组字面量。"""
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def upgrade() -> None:
    """建部门/任职表，为智能体加归属部门列，预置权限并回填租户系统角色。"""
    # users 复合外键锚点：id 虽已主键唯一，复合外键仍要求 (tenant_id,id) 上有唯一约束。
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT uq_users_tenant_id UNIQUE (tenant_id, id)"
    )

    op.execute(
        f"""
        CREATE TABLE departments (
            id          UUID         NOT NULL,
            tenant_id   UUID         NOT NULL,
            parent_id   UUID         NULL,
            name        VARCHAR(100) NOT NULL,
            code        VARCHAR(64)  NULL,
            path        TEXT         NOT NULL,
            level       INTEGER      NOT NULL,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_departments PRIMARY KEY (id),
            CONSTRAINT fk_departments_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_departments_parent FOREIGN KEY (parent_id)
                REFERENCES departments (id) ON DELETE RESTRICT,
            CONSTRAINT uq_departments_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_departments_tenant_path UNIQUE (tenant_id, path),
            CONSTRAINT ck_departments_level CHECK (level BETWEEN 1 AND 10),
            CONSTRAINT ck_departments_root CHECK ((parent_id IS NULL) = (level = 1)),
            CONSTRAINT ck_departments_name CHECK (length(btrim(name)) > 0),
            CONSTRAINT ck_departments_code CHECK (
                code IS NULL
                OR (code = lower(code) AND code ~ '^[a-z0-9_-]{{1,64}}$')),
            CONSTRAINT ck_departments_path_shape CHECK (
                path = '/' || id::text || '/'
                OR path LIKE '%/' || id::text || '/'),
            CONSTRAINT ck_departments_path_len CHECK (char_length(path) <= 400)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_departments_tenant_code
            ON departments (tenant_id, lower(code))
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_departments_parent_name
            ON departments (
                tenant_id,
                COALESCE(parent_id, '{_NIL_UUID}'::uuid),
                lower(name))
        """
    )
    op.execute(
        "CREATE INDEX ix_departments_tenant_parent ON departments (tenant_id, parent_id)"
    )
    op.execute(
        "CREATE INDEX ix_departments_tenant_path "
        "ON departments (tenant_id, path text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX ix_departments_tenant_sort "
        "ON departments (tenant_id, parent_id, sort_order, id)"
    )
    op.execute(
        """
        CREATE TRIGGER trg_departments_updated_at BEFORE UPDATE ON departments
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.execute(
        """
        CREATE TABLE user_employments (
            id             UUID         NOT NULL,
            tenant_id      UUID         NOT NULL,
            user_id        UUID         NOT NULL,
            department_id  UUID         NOT NULL,
            position       VARCHAR(100) NOT NULL DEFAULT '',
            is_current     BOOLEAN      NOT NULL DEFAULT TRUE,
            started_at     DATE         NOT NULL,
            ended_at       DATE         NULL,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_user_employments PRIMARY KEY (id),
            CONSTRAINT fk_user_employments_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_user_employments_user
                FOREIGN KEY (tenant_id, user_id)
                REFERENCES users (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_user_employments_department
                FOREIGN KEY (tenant_id, department_id)
                REFERENCES departments (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT ck_emp_current_ended CHECK (
                (is_current AND ended_at IS NULL)
                OR (NOT is_current AND ended_at IS NOT NULL)),
            CONSTRAINT ck_emp_date_range CHECK (
                ended_at IS NULL OR started_at <= ended_at)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_emp_current_user
            ON user_employments (tenant_id, user_id) WHERE is_current
        """
    )
    op.execute(
        "CREATE INDEX ix_emp_tenant_dept_current "
        "ON user_employments (tenant_id, department_id, is_current)"
    )
    op.execute(
        "CREATE INDEX ix_emp_tenant_user ON user_employments (tenant_id, user_id)"
    )
    op.execute(
        """
        CREATE TRIGGER trg_user_employments_updated_at BEFORE UPDATE ON user_employments
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.execute("ALTER TABLE agents ADD COLUMN department_id UUID")
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_department
            FOREIGN KEY (tenant_id, department_id)
            REFERENCES departments (tenant_id, id) ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_platform_no_dept
            CHECK (tenant_id IS NOT NULL OR department_id IS NULL)
        """
    )
    op.execute(
        "CREATE INDEX ix_agents_tenant_department "
        "ON agents (tenant_id, department_id)"
    )

    # 权限目录种子，已存在的编码不重复写入。
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )

    # 回填存量租户系统角色：superadmin/admin 全部新权限，viewer 仅只读。
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            (r.code = 'superadmin' AND p.code = ANY({_code_array(_ALL_CODES)}))
            OR (r.code = 'admin' AND p.code = ANY({_code_array(_ALL_CODES)}))
            OR (r.code = 'viewer' AND p.code = ANY({_code_array(_READ_CODES)}))
        )
        WHERE r.tenant_id IS NOT NULL AND r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """移除智能体部门列、任职/部门表及新增权限授权与目录。"""
    code_array = _code_array(_ALL_CODES)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({code_array})
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = ANY({code_array})")

    op.execute("DROP INDEX IF EXISTS ix_agents_tenant_department")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_platform_no_dept")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_department")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS department_id")

    op.execute("DROP TABLE IF EXISTS user_employments")
    op.execute("DROP TABLE IF EXISTS departments")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_tenant_id")
