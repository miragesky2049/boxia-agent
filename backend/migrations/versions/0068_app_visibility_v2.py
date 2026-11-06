"""应用可见范围 v2：按 (application, tenant) 隔离，推翻老的全局 visibility_mode。

老逻辑（0028/0039）：
- application.visibility_mode + application_visibility_departments / users 两张全局白名单表。

新逻辑：
- application 加 3 列：visibility_lock / visibility_template / admin_scope_mode
- 新建 app_visibility_scope（按租户隔离的可见范围主表）
- 新建 app_visibility_whitelist（白名单明细，部门/角色/用户统一）
- 预置权限码：menu:tenant-apps / page:tenant-apps / app:admin / app:admin:all /
  app:visibility:write，并授租户内置角色

说明：
- 权限码 category/action 受 permission_resources 表 CHECK 约束（0011），
  技术方案草案中的 category='app' / action='write' 不合法，落地为 button + manage/update。
- 平台租户 UUID：0067 起为 00000000-0000-0000-0000-000000100000，历史全零值一并排除。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068_app_visibility_v2"
down_revision: str | None = "0067_platform_tenant_id_reconfig"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户 UUID 双字面量：全零旧值（0067 前）+ 新配置默认值（0067 后）；迁移不得 import 业务代码
_PLATFORM_TENANT_IDS = (
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000100000",
)

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:tenant-apps", "应用配置", "menu", "view", 17, "租户侧产品级应用管理入口"),
    ("page:tenant-apps", "应用配置页面", "page", "view", 117, "租户应用可见范围配置页面"),
    ("app:admin", "应用管理", "button", "manage", 407, "可管理本租户内产品级应用的租户侧配置"),
    ("app:admin:all", "应用管理全部", "button", "manage", 408, "租户内所有应用的管理范围不受限"),
    ("app:visibility:write", "可见范围编辑", "button", "update", 409, "可修改应用可见范围"),
)

# 租户侧授权口径：superadmin 全部五码；admin 不含 app:admin:all（管理范围不受限仅超管）
_TENANT_SUPERADMIN_CODES = tuple(item[0] for item in _PERMISSIONS)
_TENANT_ADMIN_CODES = (
    "menu:tenant-apps",
    "page:tenant-apps",
    "app:admin",
    "app:visibility:write",
)


def _permission_values() -> str:
    return ",\n            ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def _platform_tenant_array() -> str:
    return "ARRAY[" + ", ".join(f"'{item}'::uuid" for item in _PLATFORM_TENANT_IDS) + "]"


def _grant_sql(codes: Sequence[str], role_code: str) -> str:
    return f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = ANY({_code_array(codes)})
        WHERE r.is_system = TRUE
          AND r.code = '{role_code}'
          AND (r.tenant_id IS NULL OR r.tenant_id <> ALL({_platform_tenant_array()}))
        ON CONFLICT DO NOTHING
    """


def upgrade() -> None:
    # 1. DROP 老表与老列（列上 CHECK 约束随列一起消失）
    op.execute("DROP TABLE IF EXISTS application_visibility_users")
    op.execute("DROP TABLE IF EXISTS application_visibility_departments")
    op.execute("ALTER TABLE application DROP COLUMN IF EXISTS visibility_mode")

    # 2. application 加新列（admin_scope_mode 默认 creator_only 为未来租户级应用预留；
    #    产品级应用创建路径由 service 显式写 all_admin）
    op.execute(
        "ALTER TABLE application ADD COLUMN visibility_lock BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE application ADD COLUMN visibility_template VARCHAR(16) NOT NULL DEFAULT 'all'"
    )
    op.execute(
        "ALTER TABLE application ADD COLUMN admin_scope_mode VARCHAR(20) NOT NULL DEFAULT 'creator_only'"
    )
    op.execute(
        "ALTER TABLE application ADD CONSTRAINT ck_application_admin_scope_mode "
        "CHECK (admin_scope_mode IN ('creator_only', 'mgmt_unit', 'all_admin'))"
    )
    op.execute(
        "ALTER TABLE application ADD CONSTRAINT ck_application_visibility_template "
        "CHECK (visibility_template IN ('all', 'whitelist'))"
    )
    # 存量均为产品级应用（owner_type='platform'），管理范围按 all_admin 口径回填；
    # creator_only 默认值仅对未来租户级应用的新建路径生效
    op.execute(
        "UPDATE application SET admin_scope_mode = 'all_admin' WHERE owner_type = 'platform'"
    )

    # 3. 可见范围主表：每 (应用, 租户) 至多一行
    op.execute(
        """
        CREATE TABLE app_visibility_scope (
            id              UUID PRIMARY KEY,
            application_id  UUID NOT NULL REFERENCES application(id) ON DELETE CASCADE,
            tenant_id       UUID NOT NULL REFERENCES tenants(id),
            visibility      VARCHAR(16) NOT NULL DEFAULT 'all',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_app_visibility_scope UNIQUE (application_id, tenant_id),
            CONSTRAINT ck_app_visibility_scope CHECK (visibility IN ('all', 'whitelist'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_app_visibility_scope_tenant ON app_visibility_scope(tenant_id)"
    )

    # 4. 白名单明细：subject_id 无外键，靠查询 JOIN 隐式过滤孤儿（见 0068 设计说明）
    op.execute(
        """
        CREATE TABLE app_visibility_whitelist (
            id              UUID PRIMARY KEY,
            scope_id        UUID NOT NULL REFERENCES app_visibility_scope(id) ON DELETE CASCADE,
            subject_type    VARCHAR(16) NOT NULL,
            subject_id      UUID NOT NULL,
            include_subtree BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_whitelist_subject_type CHECK (subject_type IN ('DEPARTMENT', 'ROLE', 'USER'))
        )
        """
    )
    op.execute("CREATE INDEX ix_whitelist_scope ON app_visibility_whitelist(scope_id)")
    op.execute(
        "CREATE INDEX ix_whitelist_subject ON app_visibility_whitelist(subject_type, subject_id)"
    )

    # 5. 预置权限码 + 租户内置角色授权（写法沿用 0058，按角色 code 匹配，不写死 UUID）
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(_grant_sql(_TENANT_SUPERADMIN_CODES, "superadmin"))
    op.execute(_grant_sql(_TENANT_ADMIN_CODES, "admin"))


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources
            WHERE code = ANY({_code_array(_TENANT_SUPERADMIN_CODES)})
        )
        """
    )
    op.execute(
        f"DELETE FROM permission_resources WHERE code = ANY({_code_array(_TENANT_SUPERADMIN_CODES)})"
    )
    op.execute("DROP TABLE IF EXISTS app_visibility_whitelist")
    op.execute("DROP TABLE IF EXISTS app_visibility_scope")
    op.execute("ALTER TABLE application DROP CONSTRAINT IF EXISTS ck_application_admin_scope_mode")
    op.execute(
        "ALTER TABLE application DROP CONSTRAINT IF EXISTS ck_application_visibility_template"
    )
    op.execute("ALTER TABLE application DROP COLUMN IF EXISTS admin_scope_mode")
    op.execute("ALTER TABLE application DROP COLUMN IF EXISTS visibility_template")
    op.execute("ALTER TABLE application DROP COLUMN IF EXISTS visibility_lock")
    op.execute(
        "ALTER TABLE application ADD COLUMN visibility_mode VARCHAR(20) NOT NULL DEFAULT 'all'"
    )
    op.execute(
        "ALTER TABLE application ADD CONSTRAINT ck_application_visibility_mode "
        "CHECK (visibility_mode IN ('all', 'custom'))"
    )
