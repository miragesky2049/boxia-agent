"""管理单元（租户自定义业务单元树 + 标签）与行级数据权限策略。

新增 mgmt_units / agent_mgmt_units / data_scope_policies / data_scope_policy_units 四张表；
agents 增加 mgmt_unit_id（归属业务单元）与 created_by（创建者）两列，并把租户智能体的
所属部门收紧为必填（存量数据回填到各租户根部门）。新增管理单元与数据范围权限码，
并回填存量租户系统角色。

Revision ID: 0016_mgmt_units_data_scope
Revises: 0015_organization
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_mgmt_units_data_scope"
down_revision: str | None = "0015_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NIL_UUID = "00000000-0000-0000-0000-000000000000"

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:mgmt-units", "管理单元", "menu", "view", 47, ""),
    ("page:mgmt-units", "管理单元页面", "page", "view", 147, ""),
    ("button:mgmt-unit:create", "管理单元-新建", "button", "create", 380, ""),
    ("button:mgmt-unit:update", "管理单元-编辑", "button", "update", 381, ""),
    ("button:mgmt-unit:delete", "管理单元-删除", "button", "delete", 382, ""),
    ("button:data-scope:manage", "数据范围-维护", "button", "manage", 383, ""),
)

_READ_CODES = ("menu:mgmt-units", "page:mgmt-units")
_WRITE_CODES = (
    "button:mgmt-unit:create",
    "button:mgmt-unit:update",
    "button:mgmt-unit:delete",
    "button:data-scope:manage",
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
    """建管理单元与数据权限表，agents 加列并收紧部门必填，预置权限。"""
    op.execute(
        f"""
        CREATE TABLE mgmt_units (
            id          UUID         NOT NULL,
            tenant_id   UUID         NOT NULL,
            unit_type   VARCHAR(20)  NOT NULL,
            parent_id   UUID         NULL,
            name        VARCHAR(100) NOT NULL,
            code        VARCHAR(64)  NULL,
            path        TEXT         NOT NULL,
            level       INTEGER      NOT NULL,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            attrs       JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_mgmt_units PRIMARY KEY (id),
            CONSTRAINT fk_mgmt_units_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_mgmt_units_parent FOREIGN KEY (parent_id)
                REFERENCES mgmt_units (id) ON DELETE RESTRICT,
            CONSTRAINT uq_mgmt_units_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_mgmt_units_tenant_path UNIQUE (tenant_id, path),
            CONSTRAINT ck_mgmt_units_type CHECK (
                unit_type IN ('business_line', 'store', 'region', 'project', 'tag')),
            CONSTRAINT ck_mgmt_units_level CHECK (level BETWEEN 1 AND 10),
            CONSTRAINT ck_mgmt_units_root CHECK ((parent_id IS NULL) = (level = 1)),
            CONSTRAINT ck_mgmt_units_tag_flat CHECK (unit_type <> 'tag' OR parent_id IS NULL),
            CONSTRAINT ck_mgmt_units_name CHECK (length(btrim(name)) > 0),
            CONSTRAINT ck_mgmt_units_code CHECK (
                code IS NULL
                OR (code = lower(code) AND code ~ '^[a-z0-9_-]{{1,64}}$')),
            CONSTRAINT ck_mgmt_units_path_shape CHECK (
                path = '/' || id::text || '/'
                OR path LIKE '%/' || id::text || '/')
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_mgmt_units_tenant_code
            ON mgmt_units (tenant_id, lower(code))
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_mgmt_units_parent_name
            ON mgmt_units (
                tenant_id,
                COALESCE(parent_id, '{_NIL_UUID}'::uuid),
                lower(name))
        """
    )
    op.execute(
        "CREATE INDEX ix_mgmt_units_tenant_parent ON mgmt_units (tenant_id, parent_id)"
    )
    op.execute(
        "CREATE INDEX ix_mgmt_units_tenant_path "
        "ON mgmt_units (tenant_id, path text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX ix_mgmt_units_tenant_type "
        "ON mgmt_units (tenant_id, unit_type, is_active)"
    )
    op.execute(
        "CREATE INDEX ix_mgmt_units_tenant_sort "
        "ON mgmt_units (tenant_id, parent_id, sort_order, id)"
    )
    op.execute(
        """
        CREATE TRIGGER trg_mgmt_units_updated_at BEFORE UPDATE ON mgmt_units
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.execute(
        """
        CREATE TABLE agent_mgmt_units (
            agent_id   UUID NOT NULL,
            unit_id    UUID NOT NULL,
            CONSTRAINT pk_agent_mgmt_units PRIMARY KEY (agent_id, unit_id),
            CONSTRAINT fk_amu_agent FOREIGN KEY (agent_id)
                REFERENCES agents (id) ON DELETE CASCADE,
            CONSTRAINT fk_amu_unit FOREIGN KEY (unit_id)
                REFERENCES mgmt_units (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_mgmt_units_unit ON agent_mgmt_units (unit_id)"
    )

    op.execute(
        """
        CREATE TABLE data_scope_policies (
            id            UUID         NOT NULL,
            tenant_id     UUID         NOT NULL,
            subject_type  VARCHAR(10)  NOT NULL,
            subject_id    UUID         NOT NULL,
            scope_type    VARCHAR(20)  NOT NULL,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_data_scope_policies PRIMARY KEY (id),
            CONSTRAINT fk_data_scope_policies_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT uq_data_scope_subject UNIQUE (tenant_id, subject_type, subject_id),
            CONSTRAINT ck_data_scope_subject_type CHECK (subject_type IN ('role', 'user')),
            CONSTRAINT ck_data_scope_scope_type CHECK (
                scope_type IN ('all', 'dept_and_sub', 'dept_only',
                               'self', 'custom', 'abac_tag'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_data_scope_policy_subject "
        "ON data_scope_policies (subject_type, subject_id)"
    )
    op.execute(
        """
        CREATE TRIGGER trg_data_scope_policies_updated_at
            BEFORE UPDATE ON data_scope_policies
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.execute(
        """
        CREATE TABLE data_scope_policy_units (
            policy_id  UUID NOT NULL,
            unit_id    UUID NOT NULL,
            CONSTRAINT pk_data_scope_policy_units PRIMARY KEY (policy_id, unit_id),
            CONSTRAINT fk_dspu_policy FOREIGN KEY (policy_id)
                REFERENCES data_scope_policies (id) ON DELETE CASCADE,
            CONSTRAINT fk_dspu_unit FOREIGN KEY (unit_id)
                REFERENCES mgmt_units (id) ON DELETE RESTRICT
        )
        """
    )

    # agents 加列：归属业务单元 + 创建者。
    op.execute("ALTER TABLE agents ADD COLUMN mgmt_unit_id UUID")
    op.execute("ALTER TABLE agents ADD COLUMN created_by UUID")
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_mgmt_unit
            FOREIGN KEY (tenant_id, mgmt_unit_id)
            REFERENCES mgmt_units (tenant_id, id) ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_created_by
            FOREIGN KEY (tenant_id, created_by)
            REFERENCES users (tenant_id, id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_platform_no_unit
            CHECK (tenant_id IS NOT NULL OR mgmt_unit_id IS NULL)
        """
    )

    # 存量租户智能体部门回填：未填部门的落到本租户根部门，再收紧为必填。
    op.execute(
        """
        UPDATE agents a
        SET department_id = d.id
        FROM (
            SELECT DISTINCT ON (tenant_id) tenant_id, id
            FROM departments
            WHERE level = 1
            ORDER BY tenant_id, sort_order, id
        ) d
        WHERE a.tenant_id = d.tenant_id AND a.department_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_tenant_dept_required
            CHECK (tenant_id IS NULL OR department_id IS NOT NULL)
        """
    )
    op.execute(
        "CREATE INDEX ix_agents_tenant_created_by ON agents (tenant_id, created_by)"
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

    # 回填存量租户系统角色：superadmin/admin 全部新权限，viewer 仅只读菜单。
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
    """移除新增权限与表，agents 去掉新列与必填约束。"""
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

    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_tenant_dept_required"
    )
    op.execute("DROP INDEX IF EXISTS ix_agents_tenant_created_by")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_platform_no_unit")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_created_by")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_mgmt_unit")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS mgmt_unit_id")

    op.execute("DROP TABLE IF EXISTS data_scope_policy_units")
    op.execute("DROP TABLE IF EXISTS data_scope_policies")
    op.execute("DROP TABLE IF EXISTS agent_mgmt_units")
    op.execute("DROP TABLE IF EXISTS mgmt_units")
