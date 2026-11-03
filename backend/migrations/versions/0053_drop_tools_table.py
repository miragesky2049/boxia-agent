"""下线老 tools 表：数据并入统一 resource 表后物理删除，并清理工具权限码。

Revision ID: 0053_drop_tools_table
Revises: 0052_conversation_debug_user
Create Date: 2026-11-03

设计要点：
- 老 tools 表数据搬迁到 resource（type='tool'），保留 id，
  平台工具 owner_type='platform'，租户工具 owner_type='tenant' + owner_id=tenant_id；
  老 description 并入 config.description，使 resource_grants 授权记录继续有效
- 删除工具管理相关 9 个权限码，同步清理 role_permissions 引用
- 最后 DROP tools；工具的角色级数据授权（resource_grants 复数表）保留
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0053_drop_tools_table"
down_revision: str | None = "0052_conversation_debug_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLATFORM_TENANT = "00000000-0000-0000-0000-000000000000"

_TOOL_PERMISSION_CODES = (
    "menu:tools",
    "page:tools",
    "button:tool:create",
    "button:tool:update",
    "button:tool:delete",
    "tool:create",
    "tool:read",
    "tool:update",
    "tool:delete",
)


def upgrade() -> None:
    # 1. 数据搬迁：tools → resource（type='tool'），保留 id；description 并入 config
    op.execute(
        f"""
        INSERT INTO resource
            (id, type, owner_type, owner_id, name, config, version,
             is_enabled, is_deprecated, created_at)
        SELECT
            t.id,
            'tool',
            CASE WHEN t.tenant_id = '{_PLATFORM_TENANT}' THEN 'platform' ELSE 'tenant' END,
            CASE WHEN t.tenant_id = '{_PLATFORM_TENANT}' THEN NULL ELSE t.tenant_id END,
            t.name,
            CASE
                WHEN COALESCE(t.description, '') = '' THEN t.config
                ELSE jsonb_build_object('description', t.description) || t.config
            END,
            1,
            t.is_enabled,
            FALSE,
            t.created_at
        FROM tools t
        ON CONFLICT (id) DO NOTHING
        """
    )

    # 2. 清理工具权限：先删 role_permissions，再删 permission_resources
    codes_literal = ", ".join(f"'{code}'" for code in _TOOL_PERMISSION_CODES)
    op.execute(
        f"DELETE FROM role_permissions WHERE permission_id IN "
        f"(SELECT id FROM permission_resources WHERE code IN ({codes_literal}))"
    )
    op.execute(f"DELETE FROM permission_resources WHERE code IN ({codes_literal})")

    # 3. DROP 老表
    op.execute("DROP TABLE IF EXISTS tools CASCADE")


def downgrade() -> None:
    # 老表不做 downgrade：数据已并入 resource 表，回滚无意义
    raise NotImplementedError("tools 表已并入 resource，不支持回滚")
