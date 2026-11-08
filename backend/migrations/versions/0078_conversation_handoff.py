"""0078 conversation 接管路由态两列（M4 PRD F14.9，U7 裁决）。

背景（docs/agent-m4-prd.md F14.9）：
- active_application_id：发言权指针，NULL=归属应用（application_id）应答；
  FK ON DELETE SET NULL——接管目标应用被删除时自动归位，不残留悬空路由；
- handoff_chain：接管顺序的应用 id 数组（归属应用为首元素），JSONB 默认 '[]'；
  链深≤3 + 去环判定在 internal/domain/agent/handoff（纯函数），本表只管存取；
- conversation 表现状无 metadata 类扩展列（review 修正：非"复用 metadata"），
  两列随本迁移一并加。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0078_conversation_handoff"
down_revision: str | None = "0077_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation
            ADD COLUMN active_application_id UUID NULL,
            ADD CONSTRAINT fk_conversation_active_application
                FOREIGN KEY (active_application_id)
                REFERENCES application (id) ON DELETE SET NULL
        """
    )
    op.execute(
        "ALTER TABLE conversation ADD COLUMN handoff_chain JSONB "
        "NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversation DROP CONSTRAINT IF EXISTS fk_conversation_active_application")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS handoff_chain")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS active_application_id")
