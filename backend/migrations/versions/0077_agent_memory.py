"""0077 agent_memory 长期记忆表（M4 PRD F16.2）。

背景（docs/agent-m4-prd.md F16）：
- 跨会话沉淀用户偏好/事实（kind=preference|fact|episode），抽取管线（F16.3）写入、
  召回注入（F16.4）读取；用户管理面（F16.6）可查看/删除/清空（隐私硬条件）；
- 列类型口径对齐 conversation 表：tenant_id/user_id/application_id 均为 UUID；
- 不做数据库唯一约束控重：近重复由抽取管线内 LLM 对照现有记忆给 update/去重
  指令（F16.3，单段管线），容量由 maxMemories FIFO 归档兜底；
- **embedding 列不建**（F16.5 开工时 ALTER + 历史回填，pgvector 扩展 0022 已就绪，
  理由同 U10 不预留口径）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0077_agent_memory"
down_revision: str | None = "0076_conversation_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_memory (
            id              UUID         NOT NULL,
            tenant_id       UUID         NOT NULL,
            application_id  UUID         NOT NULL,
            user_id         UUID         NOT NULL,
            kind            VARCHAR(20)  NOT NULL,
            content         VARCHAR(500) NOT NULL,
            status          VARCHAR(20)  NOT NULL DEFAULT 'active',
            source_run_id   UUID,
            metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            hit_count       INT          NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_agent_memory PRIMARY KEY (id),
            CONSTRAINT fk_agent_memory_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_agent_memory_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE,
            CONSTRAINT ck_agent_memory_kind CHECK (kind IN ('preference', 'fact', 'episode')),
            CONSTRAINT ck_agent_memory_status CHECK (status IN ('active', 'archived'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_memory_scope "
        "ON agent_memory (tenant_id, application_id, user_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_memory")
