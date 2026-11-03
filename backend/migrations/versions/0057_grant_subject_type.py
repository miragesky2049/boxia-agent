"""整租户授权显式化：resource_grants 加 subject_type，重建作用域 CHECK 与部分唯一索引。

Revision ID: 0057_grant_subject_type
Revises: 0056_resource_review
Create Date: 2026-11-03

设计要点（见 docs/authorization-execution-plan.md §2.4，D-2 路线 1 / D-1 已随 0054 交付）：
- 停机维护窗口内单次完成：加列 → 回填 → 换 CHECK → 重建索引，无旧代码撞新 CHECK 的窗口。
- role_id IS NULL 回填 subject_type='tenant'（全员可见+新增角色自动继承语义不变），其余 'role'。
- 本迁移不删除任何数据；downgrade 恢复旧 ck_resource_grants_scope 与三个旧部分唯一索引。
- 回填统计打日志便于核对；执行前需备份 resource_grants（高风险 DDL）。
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057_grant_subject_type"
down_revision: str | None = "0056_resource_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

# 平台租户全零 UUID（internal.domain.constants.PLATFORM_TENANT_ID 字面量，迁移不得 import 业务代码）
_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    conn = op.get_bind()

    # 1) 加列，默认 role
    op.add_column(
        "resource_grants",
        sa.Column(
            "subject_type",
            sa.String(length=10),
            nullable=False,
            server_default="role",
            comment="tenant=整租户全员可见（role_id 必须为空）；role=按角色授权",
        ),
    )

    # 2) 回填 + 统计留档（§2.4：迁移脚本须在日志中输出回填统计）
    conn.execute(
        sa.text("UPDATE resource_grants SET subject_type = 'tenant' WHERE role_id IS NULL")
    )
    tenant_wide = conn.execute(
        sa.text("SELECT count(*) FROM resource_grants WHERE subject_type = 'tenant'")
    ).scalar()
    role_scoped = conn.execute(
        sa.text("SELECT count(*) FROM resource_grants WHERE subject_type = 'role'")
    ).scalar()
    logger.info(
        "0057 回填统计：subject_type=tenant %s 条，subject_type=role %s 条",
        tenant_wide,
        role_scoped,
    )

    # 3) 作用域 CHECK：tenant 档必须无 role_id，role 档必须有 role_id
    conn.execute(
        sa.text("ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_scope")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE resource_grants ADD CONSTRAINT ck_resource_grants_subject CHECK ("
            "(subject_type = 'tenant' AND role_id IS NULL) "
            "OR (subject_type = 'role' AND role_id IS NOT NULL))"
        )
    )

    # 4) 唯一索引重建：新旧谓词一一对应，同窗口内完成切换
    op.create_index(
        "ux_resource_grants_tenant_subject",
        "resource_grants",
        ["resource_type", "resource_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("subject_type = 'tenant'"),
    )
    op.create_index(
        "ux_resource_grants_role_subject",
        "resource_grants",
        ["resource_type", "resource_id", "tenant_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("subject_type = 'role'"),
    )
    op.create_index(
        "ux_resource_grants_platform_role_subject",
        "resource_grants",
        ["resource_type", "resource_id", "role_id"],
        unique=True,
        postgresql_where=sa.text(f"subject_type = 'role' AND tenant_id = '{_PLATFORM_TENANT_ID}'"),
    )
    op.drop_index("ux_resource_grants_tenant_wide", table_name="resource_grants")
    op.drop_index("ux_resource_grants_role", table_name="resource_grants")
    op.drop_index("ux_resource_grants_platform_role", table_name="resource_grants")


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_index("ux_resource_grants_platform_role_subject", table_name="resource_grants")
    op.drop_index("ux_resource_grants_role_subject", table_name="resource_grants")
    op.drop_index("ux_resource_grants_tenant_subject", table_name="resource_grants")

    # 恢复旧 ck_resource_grants_scope（tenant_id 列本身 NOT NULL，旧约束恒真，可直接恢复）
    conn.execute(
        sa.text("ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_subject")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE resource_grants ADD CONSTRAINT ck_resource_grants_scope "
            "CHECK (role_id IS NOT NULL OR tenant_id IS NOT NULL)"
        )
    )

    # 恢复三个旧部分唯一索引（谓词回到 role_id 空/非空口径）
    op.create_index(
        "ux_resource_grants_tenant_wide",
        "resource_grants",
        ["resource_type", "resource_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("role_id IS NULL"),
    )
    op.create_index(
        "ux_resource_grants_role",
        "resource_grants",
        ["resource_type", "resource_id", "tenant_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )
    op.create_index(
        "ux_resource_grants_platform_role",
        "resource_grants",
        ["resource_type", "resource_id", "role_id"],
        unique=True,
        postgresql_where=sa.text(f"tenant_id = '{_PLATFORM_TENANT_ID}' AND role_id IS NOT NULL"),
    )

    op.drop_column("resource_grants", "subject_type")
