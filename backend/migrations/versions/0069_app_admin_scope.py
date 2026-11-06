"""应用管理范围（二期）：app_admin_scope 关联表 + 管理范围编辑权限码。

- 新建 app_admin_scope（应用 ↔ 管理单元），供 admin_scope_mode='mgmt_unit' 的应用
  判定"当前用户被授予的管理单元是否覆盖该应用"。
- 预置权限码 app:admin_scope:write，并授租户内置角色 superadmin / admin。

说明：
- 权限码 category/action 受 permission_resources 表 CHECK 约束（0011），
  技术方案草案中的 category='app' / action='write' 不合法，落地为 button + update。
- mgmt_unit_id 对 mgmt_units CASCADE：管理单元删除时关联自动消失，
  读取时再 JOIN 过滤历史孤儿，口径与 0068 白名单一致。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0069_app_admin_scope"
down_revision: str | None = "0068_app_visibility_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户 UUID 双字面量：全零旧值（0067 前）+ 新配置默认值（0067 后）；迁移不得 import 业务代码
_PLATFORM_TENANT_IDS = (
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000100000",
)

_PERMISSION_CODE = "app:admin_scope:write"


def _platform_tenant_array() -> str:
    return "ARRAY[" + ", ".join(f"'{item}'::uuid" for item in _PLATFORM_TENANT_IDS) + "]"


def _grant_sql(role_code: str) -> str:
    return f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = '{_PERMISSION_CODE}'
        WHERE r.is_system = TRUE
          AND r.code = '{role_code}'
          AND (r.tenant_id IS NULL OR r.tenant_id <> ALL({_platform_tenant_array()}))
        ON CONFLICT DO NOTHING
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_admin_scope (
            id              UUID PRIMARY KEY,
            application_id  UUID NOT NULL REFERENCES application(id) ON DELETE CASCADE,
            tenant_id       UUID NOT NULL REFERENCES tenants(id),
            mgmt_unit_id    UUID NOT NULL REFERENCES mgmt_units(id) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_app_admin_scope UNIQUE (application_id, mgmt_unit_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_admin_scope_app ON app_admin_scope(application_id)")
    op.execute("CREATE INDEX ix_admin_scope_unit ON app_admin_scope(mgmt_unit_id)")

    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            (gen_random_uuid(), '{_PERMISSION_CODE}', '管理范围编辑', 'button', 'update',
             '可修改应用关联的管理单元', 410, TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(_grant_sql("superadmin"))
    op.execute(_grant_sql("admin"))


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = '{_PERMISSION_CODE}'
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = '{_PERMISSION_CODE}'")
    op.execute("DROP TABLE IF EXISTS app_admin_scope")
