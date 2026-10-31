"""0046 application 加 published_graph_version：发布动作快照点。

Revision ID: 0046_published_graph_version
Revises: 0045_align_coze_naming
Create Date: 2026-10-31

设计要点：
- draft = application_graph_version 表中最新一版（admin 保存即写新版本）
- live = 用户端实际跑的版本；通过 application.published_graph_version 指向
- 未发布时 published_graph_version = NULL，运行时回退到 latest（向后兼容）
- 发布动作：把当前 latest 版本号写入 published_graph_version，并失效缓存
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_published_graph_version"
down_revision: str | None = "0045_align_coze_naming"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application",
        sa.Column(
            "published_graph_version",
            sa.Integer(),
            nullable=True,
            comment="用户端实际运行的整图版本号；NULL 表示未发布，回退到 latest",
        ),
    )


def downgrade() -> None:
    op.drop_column("application", "published_graph_version")
