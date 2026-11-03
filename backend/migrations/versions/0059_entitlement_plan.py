"""0059 套餐模板：entitlement_plan + entitlement_plan_item。

Revision ID: 0059_entitlement_plan
Revises: 0058_entitlement_permissions
Create Date: 2026-11-03

设计要点（见 docs/authorization-execution-plan.md P3-3）：
- 模板 = 条目集合（五类对象）+ 默认 auth_type / 期限（duration_days）/ 默认 quota；
  开通走 EntitlementService.apply_plan → 复用 apply_batch，权益行仍落双表，模板不落权益。
- code 全局唯一（平台级定义，不区分租户）；duration_days NULL 表示默认不限期。
- 条目外键 ON DELETE CASCADE：删模板不影响已开通权益，只清定义行。
- 存量无回填：新表。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_entitlement_plan"
down_revision: str | None = "0058_entitlement_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entitlement_plan (
            id            UUID         NOT NULL,
            code          VARCHAR(64)  NOT NULL,
            name          VARCHAR(128) NOT NULL,
            description   TEXT         NOT NULL DEFAULT '',
            auth_type     VARCHAR(16)  NOT NULL DEFAULT 'FORMAL',
            duration_days INTEGER      NULL,
            quota_json    JSONB        NOT NULL DEFAULT '{}'::jsonb,
            is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_entitlement_plan PRIMARY KEY (id),
            CONSTRAINT uq_entitlement_plan_code UNIQUE (code),
            CONSTRAINT ck_entitlement_plan_auth_type
                CHECK (auth_type IN ('FORMAL', 'TRIAL', 'GIFT')),
            CONSTRAINT ck_entitlement_plan_duration CHECK (duration_days IS NULL OR duration_days > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entitlement_plan_item (
            id          UUID        NOT NULL,
            plan_id     UUID        NOT NULL,
            object_type VARCHAR(16) NOT NULL,
            object_id   UUID        NOT NULL,
            CONSTRAINT pk_entitlement_plan_item PRIMARY KEY (id),
            CONSTRAINT fk_entitlement_plan_item_plan
                FOREIGN KEY (plan_id) REFERENCES entitlement_plan (id) ON DELETE CASCADE,
            CONSTRAINT uq_entitlement_plan_item UNIQUE (plan_id, object_type, object_id),
            CONSTRAINT ck_entitlement_plan_item_type
                CHECK (object_type IN ('app', 'tool', 'skill', 'prompt', 'knowledge'))
        )
        """
    )
    op.execute("CREATE INDEX ix_entitlement_plan_item_plan ON entitlement_plan_item (plan_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_entitlement_plan_item_plan")
    op.execute("DROP TABLE IF EXISTS entitlement_plan_item")
    op.execute("DROP TABLE IF EXISTS entitlement_plan")
