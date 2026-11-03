"""资源审核：resource 加 review_status/reviewed_by/reviewed_at/review_remark/created_by。

Revision ID: 0056_resource_review
Revises: 0055_resource_grant_lifecycle
Create Date: 2026-11-03

设计要点（见 docs/authorization-execution-plan.md §2.3，假设 A5）：
- review_status 默认 'approved'，存量行由 DEFAULT 直接回填，平台资源保持 approved；
  租户自建资源写入 pending（P1-9 审核流），审核通过后角色授权候选才可见。
- created_by 存量置 NULL（历史无记录来源）；新建资源必须写入当前管理员 ID，
  供「审核人不得审核自己创建的资源」职责分离校验（created_by IS NULL 的历史资源放行）。
- ix_resource_review_status(review_status, owner_type) 服务审核队列与候选过滤查询。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_resource_review"
down_revision: str | None = "0055_resource_grant_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource",
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="approved",
            comment="pending / approved / rejected",
        ),
    )
    op.add_column(
        "resource",
        sa.Column("reviewed_by", sa.Uuid(as_uuid=True), nullable=True, comment="审核人"),
    )
    op.add_column(
        "resource",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True, comment="审核时间"),
    )
    op.add_column(
        "resource",
        sa.Column(
            "review_remark", sa.Text(), nullable=False, server_default="", comment="审核意见"
        ),
    )
    op.add_column(
        "resource",
        sa.Column(
            "created_by",
            sa.Uuid(as_uuid=True),
            nullable=True,
            comment="创建人（职责分离校验用，历史存量 NULL）",
        ),
    )

    op.create_check_constraint(
        "ck_resource_review_status",
        "resource",
        "review_status IN ('pending', 'approved', 'rejected')",
    )
    op.create_index("ix_resource_review_status", "resource", ["review_status", "owner_type"])


def downgrade() -> None:
    op.drop_index("ix_resource_review_status", table_name="resource")
    op.drop_constraint("ck_resource_review_status", "resource", type_="check")
    for column in ("created_by", "review_remark", "reviewed_at", "reviewed_by", "review_status"):
        op.drop_column("resource", column)
