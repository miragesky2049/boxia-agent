"""管理单元改造：部门/人员关联 + 用户管理单元授权；废弃旧数据范围策略。

新增 mgmt_unit_departments / mgmt_unit_users / user_mgmt_unit_grants 三张表；
废弃 agent_mgmt_units、data_scope_policies、data_scope_policy_units；
agents.mgmt_unit_id 列与相关外键/约束删除；mgmt_units.unit_type 收敛为单一 'unit'。

Revision ID: 0017_mgmt_unit_rebindings
Revises: 0016_mgmt_units_data_scope
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_mgmt_unit_rebindings"
down_revision: str | None = "0016_mgmt_units_data_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name, category, action, sort_order, description)
_NEW_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("button:mgmt-unit:grant", "管理单元-授权用户", "button", "manage", 384, ""),
)

_DEPRECATED_CODES = ("button:data-scope:manage",)


def _permission_values() -> str:
    """构造权限目录批量插入的 VALUES 子句。"""
    return ",\n        ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _NEW_PERMISSIONS
    )


def _code_array(codes: tuple[str, ...]) -> str:
    """把权限码元组渲染为 PostgreSQL 字符串数组字面量。"""
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def upgrade() -> None:
    """建新表、废弃旧表与旧列、收敛单元类型、切换权限码。"""
    # 1) 管理单元关联部门（含子树开关）
    op.execute(
        """
        CREATE TABLE mgmt_unit_departments (
            unit_id          UUID         NOT NULL,
            department_id    UUID         NOT NULL,
            include_subtree BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_mgmt_unit_departments PRIMARY KEY (unit_id, department_id),
            CONSTRAINT fk_mud_unit FOREIGN KEY (unit_id)
                REFERENCES mgmt_units (id) ON DELETE CASCADE,
            CONSTRAINT fk_mud_department FOREIGN KEY (department_id)
                REFERENCES departments (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_mud_department ON mgmt_unit_departments (department_id)"
    )

    # 2) 管理单元关联人员
    op.execute(
        """
        CREATE TABLE mgmt_unit_users (
            unit_id     UUID         NOT NULL,
            user_id     UUID         NOT NULL,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_mgmt_unit_users PRIMARY KEY (unit_id, user_id),
            CONSTRAINT fk_muu_unit FOREIGN KEY (unit_id)
                REFERENCES mgmt_units (id) ON DELETE CASCADE,
            CONSTRAINT fk_muu_user FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_muu_user ON mgmt_unit_users (user_id)")

    # 3) 用户被授权的管理单元（数据权限授权表）
    op.execute(
        """
        CREATE TABLE user_mgmt_unit_grants (
            id          UUID         NOT NULL,
            tenant_id   UUID         NOT NULL,
            user_id     UUID         NOT NULL,
            unit_id     UUID         NOT NULL,
            granted_by  UUID         NULL,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_user_mgmt_unit_grants PRIMARY KEY (id),
            CONSTRAINT uq_user_mgmt_unit_grant UNIQUE (tenant_id, user_id, unit_id),
            CONSTRAINT fk_umug_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_umug_user FOREIGN KEY (tenant_id, user_id)
                REFERENCES users (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_umug_unit FOREIGN KEY (tenant_id, unit_id)
                REFERENCES mgmt_units (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_umug_granted_by FOREIGN KEY (granted_by)
                REFERENCES admin_users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_umug_user ON user_mgmt_unit_grants (tenant_id, user_id)"
    )
    op.execute(
        "CREATE INDEX ix_umug_unit ON user_mgmt_unit_grants (tenant_id, unit_id)"
    )

    # 4) 单元类型已收敛为单一 'unit'，应用层不再区分类型，直接删除该列
    op.execute("ALTER TABLE mgmt_units DROP CONSTRAINT IF EXISTS ck_mgmt_units_type")
    op.execute("ALTER TABLE mgmt_units DROP CONSTRAINT IF EXISTS ck_mgmt_units_tag_flat")
    op.execute("ALTER TABLE mgmt_units DROP COLUMN IF EXISTS unit_type")

    # 5) agents 删除 mgmt_unit_id 列与相关外键/约束
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_mgmt_unit"
    )
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_platform_no_unit"
    )
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS mgmt_unit_id")

    # 6) 废弃旧表
    op.execute("DROP TABLE IF EXISTS agent_mgmt_units")
    op.execute("DROP TABLE IF EXISTS data_scope_policy_units")
    op.execute("DROP TABLE IF EXISTS data_scope_policies")

    # 7) 切换权限码：新增 button:mgmt-unit:grant，删除 button:data-scope:manage
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )

    # 把旧权限码替换为新权限码：角色上已授予旧码的，改写为新码（同一语义）
    op.execute(
        f"""
        UPDATE role_permissions rp
        SET permission_id = (
            SELECT id FROM permission_resources WHERE code = 'button:mgmt-unit:grant'
        )
        WHERE rp.permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_DEPRECATED_CODES)})
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_DEPRECATED_CODES)})
        )
        """
    )
    op.execute(
        f"DELETE FROM permission_resources WHERE code = ANY({_code_array(_DEPRECATED_CODES)})"
    )

    # 8) 回填租户系统角色：superadmin/admin 拥有新权限
    new_codes = _code_array(tuple(code for code, *_ in _NEW_PERMISSIONS))
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            (r.code = 'superadmin' AND p.code = ANY({new_codes}))
            OR (r.code = 'admin' AND p.code = ANY({new_codes}))
        )
        WHERE r.tenant_id IS NOT NULL AND r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """回滚：恢复 0016 结构。"""
    new_codes = _code_array(tuple(code for code, *_ in _NEW_PERMISSIONS))

    # 移除新权限码授予关系
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({new_codes})
        )
        """
    )

    # 恢复 0016 权限码
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            (gen_random_uuid(), 'button:data-scope:manage', '数据范围-维护',
             'button', 'manage', '', 383, TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )

    # 删除新表
    op.execute("DROP TABLE IF EXISTS user_mgmt_unit_grants")
    op.execute("DROP TABLE IF EXISTS mgmt_unit_users")
    op.execute("DROP TABLE IF EXISTS mgmt_unit_departments")

    # 恢复 agents.mgmt_unit_id
    op.execute("ALTER TABLE agents ADD COLUMN mgmt_unit_id UUID")
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
            ADD CONSTRAINT ck_agents_platform_no_unit
            CHECK (tenant_id IS NOT NULL OR mgmt_unit_id IS NULL)
        """
    )

    # 恢复 mgmt_units.unit_type 列与多类型约束
    op.execute(
        "ALTER TABLE mgmt_units ADD COLUMN unit_type VARCHAR(20) NOT NULL DEFAULT 'business_line'"
    )
    op.execute(
        "ALTER TABLE mgmt_units ADD CONSTRAINT ck_mgmt_units_type "
        "CHECK (unit_type IN ('business_line', 'store', 'region', 'project', 'tag'))"
    )
    op.execute(
        "ALTER TABLE mgmt_units ADD CONSTRAINT ck_mgmt_units_tag_flat "
        "CHECK (unit_type <> 'tag' OR parent_id IS NULL)"
    )

    # 恢复旧表
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
    op.execute("CREATE INDEX ix_agent_mgmt_units_unit ON agent_mgmt_units (unit_id)")

    # 清理新增权限码
    op.execute(f"DELETE FROM permission_resources WHERE code = ANY({new_codes})")
