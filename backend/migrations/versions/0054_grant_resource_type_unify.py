"""统一 resource_grants 资源类型：清理历史 agent/component 孤儿，CHECK 改为五类。

Revision ID: 0054_grant_resource_type_unify
Revises: 0053_drop_tools_table
Create Date: 2026-11-03

设计要点：
- 0037 已 DROP agents/components 且未迁移授权，0028 建 application 时也没有 INSERT FROM agents，
  因此 resource_grants 中 resource_type IN ('agent','component') 的记录全部指向不存在的对象。
  新 CHECK 不允许这两类值，必须先删除，否则 ADD CONSTRAINT 校验存量数据会失败。
- 授权类型清单与 domain 常量对齐：app / tool / skill / prompt / knowledge
  （见 internal/domain/entity/access.py 的 RESOURCE_TYPES）。
- downgrade 恢复旧 CHECK 文案；被删除的 agent/component 记录无法恢复，需靠备份还原。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_grant_resource_type_unify"
down_revision: str | None = "0053_drop_tools_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

# 历史遗留类型：对象已不存在，仅存在于授权表
_LEGACY_TYPES = ("agent", "component")
# 目标类型：与 internal/domain/entity/access.py::RESOURCE_TYPES 一致
_NEW_TYPES = ("app", "tool", "skill", "prompt", "knowledge")
# 回滚目标：0006 建立的原始 CHECK 文案
_OLD_TYPES = ("agent", "skill", "tool", "component", "prompt")


def _in_literal(types: Sequence[str]) -> str:
    return ", ".join(f"'{item}'" for item in types)


def _swap_check_constraint(conn, types: Sequence[str]) -> None:
    conn.execute(
        sa.text("ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_type")
    )
    conn.execute(
        sa.text(
            f"ALTER TABLE resource_grants ADD CONSTRAINT ck_resource_grants_type "
            f"CHECK (resource_type IN ({_in_literal(types)}))"
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    for legacy in _LEGACY_TYPES:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM resource_grants WHERE resource_type = :type"),
            {"type": legacy},
        ).scalar() or 0
        logger.info("0054：待清理 resource_grants 历史类型 %s，共 %s 条", legacy, count)

    conn.execute(
        sa.text("DELETE FROM resource_grants WHERE resource_type = ANY(:types)"),
        {"types": list(_LEGACY_TYPES)},
    )
    _swap_check_constraint(conn, _NEW_TYPES)


def downgrade() -> None:
    conn = op.get_bind()
    # 旧 CHECK 不含 app/knowledge：先删除新类型记录，否则恢复旧约束会校验失败
    conn.execute(
        sa.text("DELETE FROM resource_grants WHERE resource_type = ANY(:types)"),
        {"types": ["app", "knowledge"]},
    )
    _swap_check_constraint(conn, _OLD_TYPES)
