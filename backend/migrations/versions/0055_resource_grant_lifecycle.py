"""资源权益生命周期：resource_grant 加状态/来源/期限/配额字段 + instance 状态 CHECK 修正。

Revision ID: 0055_resource_grant_lifecycle
Revises: 0054_grant_resource_type_unify
Create Date: 2026-11-03

设计要点（含原 P0-5）：
- resource_grant（单数，产品级资源开放给租户）从"只有 granted_at"升级为完整生命周期模型：
  status / auth_source / auth_type / start_time / expire_time / quota_json / remark / granted_by。
- tenant_application_instance 的 ck_instance_status 原缺 wait_effect / expired 两个状态
  （代码与 Celery 任务已在写入，CHECK 会拦截），本迁移重建为六值。
- 本迁移属停机维护窗口（0055–0057 与 P1 代码同步发布），存量行由 DEFAULT 'active' 回填。
- downgrade 恢复旧四值 CHECK 前不会自动清理数据：若库中存在 wait_effect/expired 记录，
  ADD CONSTRAINT 校验存量会失败，需先人工清理（或按备份恢复）后再降级。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision ID 长度 ≤32：alembic_version.version_num 为 VARCHAR(32)，超长会截断报错
revision: str = "0055_resource_grant_lifecycle"
down_revision: str | None = "0054_grant_resource_type_unify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 旧 ck_instance_status 四值（0029 原文案），downgrade 时恢复
_OLD_INSTANCE_STATUS = ("active", "suspended", "disabled", "revoked")
# 新六值：补上代码已在写入的 wait_effect / expired
_NEW_INSTANCE_STATUS = ("active", "suspended", "disabled", "revoked", "wait_effect", "expired")


def _status_in_literal(types: Sequence[str]) -> str:
    return ", ".join(f"'{item}'" for item in types)


def upgrade() -> None:
    # ========== resource_grant：生命周期字段 ==========
    op.add_column(
        "resource_grant",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
            comment="active / suspended / revoked / wait_effect / expired",
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column(
            "auth_source",
            sa.String(length=20),
            nullable=False,
            server_default="OPS",
            comment="OPS=运营开通；MARKET_APPLY=市场申请开通",
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column(
            "auth_type",
            sa.String(length=20),
            nullable=False,
            server_default="FORMAL",
            comment="FORMAL / TRIAL / GIFT",
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column(
            "start_time", sa.DateTime(timezone=True), nullable=True, comment="生效时间，NULL=立即"
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column(
            "expire_time", sa.DateTime(timezone=True), nullable=True, comment="到期时间，NULL=永久"
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column(
            "quota_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="配额（本轮只存储与展示）",
        ),
    )
    op.add_column(
        "resource_grant",
        sa.Column("remark", sa.Text(), nullable=False, server_default="", comment="开通备注"),
    )
    op.add_column(
        "resource_grant",
        sa.Column("granted_by", sa.Uuid(as_uuid=True), nullable=True, comment="开通操作人"),
    )

    # ========== resource_grant：CHECK ==========
    op.create_check_constraint(
        "ck_resource_grant_status",
        "resource_grant",
        f"status IN ({_status_in_literal(('active', 'suspended', 'revoked', 'wait_effect', 'expired'))})",
    )
    op.create_check_constraint(
        "ck_resource_grant_source",
        "resource_grant",
        "auth_source IN ('OPS', 'MARKET_APPLY')",
    )
    op.create_check_constraint(
        "ck_resource_grant_type",
        "resource_grant",
        "auth_type IN ('FORMAL', 'TRIAL', 'GIFT')",
    )

    # ========== resource_grant：查询索引（权益列表按租户+状态过滤） ==========
    op.create_index("ix_resource_grant_tenant_status", "resource_grant", ["tenant_id", "status"])

    # ========== tenant_application_instance：状态 CHECK 修正（原 P0-5） ==========
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE tenant_application_instance DROP CONSTRAINT IF EXISTS ck_instance_status"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE tenant_application_instance ADD CONSTRAINT ck_instance_status "
            f"CHECK (status IN ({_status_in_literal(_NEW_INSTANCE_STATUS)}))"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # 恢复旧四值 CHECK：若存在 wait_effect/expired 记录会校验失败，需先清理（见文件头说明）
    conn.execute(
        sa.text(
            "ALTER TABLE tenant_application_instance DROP CONSTRAINT IF EXISTS ck_instance_status"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE tenant_application_instance ADD CONSTRAINT ck_instance_status "
            f"CHECK (status IN ({_status_in_literal(_OLD_INSTANCE_STATUS)}))"
        )
    )

    op.drop_index("ix_resource_grant_tenant_status", table_name="resource_grant")
    op.drop_constraint("ck_resource_grant_type", "resource_grant", type_="check")
    op.drop_constraint("ck_resource_grant_source", "resource_grant", type_="check")
    op.drop_constraint("ck_resource_grant_status", "resource_grant", type_="check")
    for column in (
        "granted_by",
        "remark",
        "quota_json",
        "expire_time",
        "start_time",
        "auth_type",
        "auth_source",
        "status",
    ):
        op.drop_column("resource_grant", column)
