"""0061 资源类型注册表：resource_type_catalog + 类型 CHECK 改外键/应用校验（P3-5）。

Revision ID: 0061_resource_type_catalog
Revises: 0060_tenant_resource_entitlement
Create Date: 2026-11-03

设计要点：
- 类型集合表驱动：新增资源类型 = 目录插一行，免改迁移与 CHECK。
- resource.type 用外键收口，DB 层保证不漂离目录；应用层仍先校验（422 早于 500）。
- resource_grants.resource_type / entitlement_plan_item.object_type 含 'app'
  （权益对象固定类型，不属于资源类型目录），无法做外键，撤销 CHECK 改应用层校验：
  权益/套餐写路径按目录（∪ app）校验，角色授权路由入口类型参数保持枚举约束。
- 种子 4 类与 RESOURCE_TABLE_TYPES 常量一致，漂移由测试拦截；is_active 支持停用。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061_resource_type_catalog"
down_revision: str | None = "0060_tenant_resource_entitlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG = "resource_type_catalog"

_SEED = [
    ("tool", "工具", "可被应用调用的 API/工具型资源", 1),
    ("skill", "技能", "编排好的技能资源", 2),
    ("prompt", "提示词", "提示词模板资源", 3),
    ("knowledge", "知识库", "知识库文档资源", 4),
]

# 撤销 CHECK 前的原口径，downgrade 还原用；库中若已插入新目录类型需先清行再降级
_RESTORE_CHECKS = [
    (
        "resource",
        "ck_resource_type",
        "type IN ('tool', 'prompt', 'skill', 'knowledge')",
    ),
    (
        "resource_grants",
        "ck_resource_grants_type",
        "resource_type IN ('app', 'tool', 'skill', 'prompt', 'knowledge')",
    ),
    (
        "entitlement_plan_item",
        "ck_entitlement_plan_item_type",
        "object_type IN ('app', 'tool', 'skill', 'prompt', 'knowledge')",
    ),
]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_CATALOG} (
            code VARCHAR(40) PRIMARY KEY,
            name VARCHAR(64) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {_CATALOG} IS "
        "'资源类型注册表（P3-5）：类型集合的事实源，新增类型插行免改迁移；app 不入表，由服务层固定放行'"
    )
    for col, comment in [
        ("code", "类型编码，resource.type 外键目标"),
        ("name", "类型显示名"),
        ("description", "类型说明"),
        ("is_active", "是否启用；停用后应用校验拒绝新引用，存量行不动"),
        ("sort_order", "展示与校验的稳定排序"),
    ]:
        op.execute(f"COMMENT ON COLUMN {_CATALOG}.{col} IS '{comment}'")
    for code, name, desc, sort in _SEED:
        op.execute(
            f"INSERT INTO {_CATALOG} (code, name, description, sort_order) "
            f"VALUES ('{code}', '{name}', '{desc}', {sort})"
        )
    op.execute("ALTER TABLE resource DROP CONSTRAINT IF EXISTS ck_resource_type")
    op.execute(
        "ALTER TABLE resource ADD CONSTRAINT fk_resource_type_catalog "
        f"FOREIGN KEY (type) REFERENCES {_CATALOG}(code)"
    )
    op.execute("ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_type")
    op.execute(
        "ALTER TABLE entitlement_plan_item DROP CONSTRAINT IF EXISTS ck_entitlement_plan_item_type"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE resource DROP CONSTRAINT IF EXISTS fk_resource_type_catalog")
    for table, name, definition in _RESTORE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({definition})")
    op.execute(f"DROP TABLE IF EXISTS {_CATALOG}")
