"""产品级租户 UUID 重配：全零 UUID → 可配置 UUID（默认 00000000-0000-0000-0000-000000100000）。

背景：
- 历史上产品级租户硬编码为全零 UUID（00000000-0000-0000-0000-000000000000）。
- 全零 UUID 通常被 ORM/框架保留，不适合作为业务主键。
- 本迁移把 tenants 表平台行与全部业务表的 tenant_id 从全零刷为新配置值。

注意：
- 迁移不得 import 业务代码（settings/constants），UUID 通过环境变量或硬编码默认值传入。
- 若目标 UUID 与当前值相同，迁移幂等跳过。
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0067_platform_tenant_id_reconfig"
down_revision: str | None = "0066_run_user_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 旧全零 UUID
_OLD_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# 新产品级租户 UUID：优先从环境变量读取，否则用默认值
_NEW_PLATFORM_TENANT_ID = os.environ.get(
    "PLATFORM_TENANT_ID", "00000000-0000-0000-0000-000000100000"
)

# tenants.code 有唯一约束：旧平台行仍占用 platform，新行必须先临时改名，最后再改回 platform
_MIGRATION_TENANT_CODE = "platform-migration"

# 所有含 tenant_id 的业务表（不含 tenants 表本身）
_BUSINESS_TABLES = (
    "application_apply",
    "audit_logs",
    "conversation",
    "departments",
    "document_chunks",
    "documents",
    "entitlement_request_log",
    "event_webhook",
    "hr_dictionaries",
    "message",
    "mgmt_units",
    "resource_grants",
    "roles",
    "run",
    "tenant_application_config",
    "tenant_application_instance",
    "tenant_resource_entitlement",
    "tenant_settings",
    "tenant_usage_ledger",
    "user_employments",
    "user_mgmt_unit_grants",
    "user_roles",
    "users",
)


def upgrade() -> None:
    """1) 插入新平台行；2) 刷业务表；3) 删除旧平台行；4) 重建谓词索引。"""
    if _OLD_PLATFORM_TENANT_ID == _NEW_PLATFORM_TENANT_ID:
        return

    # 1. 先插入新 UUID 的平台行（避免外键约束：业务表 tenant_id 必须存在于 tenants.id）。
    #    旧平台行仍占用唯一编码 platform，临时编码避开 tenants_code_key 冲突。
    op.execute(
        f"""
        INSERT INTO tenants (id, code, name, is_active)
        VALUES ('{_NEW_PLATFORM_TENANT_ID}', '{_MIGRATION_TENANT_CODE}', '产品级平台', TRUE)
        ON CONFLICT (id) DO UPDATE
        SET code = EXCLUDED.code, name = EXCLUDED.name, is_active = EXCLUDED.is_active
        """
    )

    # 2. 刷全部业务表 tenant_id 从旧全零到新 UUID
    for table in _BUSINESS_TABLES:
        op.execute(
            f"UPDATE {table} SET tenant_id = '{_NEW_PLATFORM_TENANT_ID}' "
            f"WHERE tenant_id = '{_OLD_PLATFORM_TENANT_ID}'"
        )

    # 3. 删除旧全零平台行，并把新平台行编码恢复为 platform
    op.execute(f"DELETE FROM tenants WHERE id = '{_OLD_PLATFORM_TENANT_ID}'")
    op.execute(
        f"UPDATE tenants SET code = 'platform', name = '产品级平台', is_active = TRUE "
        f"WHERE id = '{_NEW_PLATFORM_TENANT_ID}'"
    )

    # 4. 重建谓词硬编码全零 UUID 的部分唯一索引
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_code")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_code
            ON roles (lower(code))
            WHERE tenant_id = '{_NEW_PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_name")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_name
            ON roles (lower(name))
            WHERE tenant_id = '{_NEW_PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_resource_grants_platform_role_subject")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_resource_grants_platform_role_subject
            ON resource_grants (resource_type, resource_id, role_id)
            WHERE subject_type = 'role' AND tenant_id = '{_NEW_PLATFORM_TENANT_ID}'
        """
    )


def downgrade() -> None:
    """回滚：先临时插入旧平台行，再刷业务表，最后删除新平台行并恢复编码。"""
    if _OLD_PLATFORM_TENANT_ID == _NEW_PLATFORM_TENANT_ID:
        return

    # 1. 先插入旧 UUID 平台行，业务表切回旧 UUID 时必须能命中 tenants.id。
    op.execute(
        f"""
        INSERT INTO tenants (id, code, name, is_active)
        VALUES ('{_OLD_PLATFORM_TENANT_ID}', '{_MIGRATION_TENANT_CODE}', '产品级平台', TRUE)
        ON CONFLICT (id) DO UPDATE
        SET code = EXCLUDED.code, name = EXCLUDED.name, is_active = EXCLUDED.is_active
        """
    )

    # 2. 刷全部业务表 tenant_id 从新配置值回到旧全零
    for table in _BUSINESS_TABLES:
        op.execute(
            f"UPDATE {table} SET tenant_id = '{_OLD_PLATFORM_TENANT_ID}' "
            f"WHERE tenant_id = '{_NEW_PLATFORM_TENANT_ID}'"
        )

    # 3. 删除新平台行，并把旧平台行编码恢复为 platform
    op.execute(f"DELETE FROM tenants WHERE id = '{_NEW_PLATFORM_TENANT_ID}'")
    op.execute(
        f"UPDATE tenants SET code = 'platform', name = '产品级平台', is_active = TRUE "
        f"WHERE id = '{_OLD_PLATFORM_TENANT_ID}'"
    )

    # 重建谓词索引为全零
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_code")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_code
            ON roles (lower(code))
            WHERE tenant_id = '{_OLD_PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_name")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_name
            ON roles (lower(name))
            WHERE tenant_id = '{_OLD_PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_resource_grants_platform_role_subject")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_resource_grants_platform_role_subject
            ON resource_grants (resource_type, resource_id, role_id)
            WHERE subject_type = 'role' AND tenant_id = '{_OLD_PLATFORM_TENANT_ID}'
        """
    )
