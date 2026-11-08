"""0079 评测五表（M4 PRD F18.1）。

背景（docs/agent-m4-prd.md F18）：
- eval_dataset/eval_case：数据集与用例（input JSONB 含 message/images/inputs/
  conversation_seed；expected_tool_calls 支持 must_call/must_not_call 轨迹断言）；
- eval_evaluator：租户级评估器库（rule 纯代码断言 / llm_judge 走 F19.1 唯一内核）；
- eval_run/eval_result：一次批跑与其逐 case 判定；eval_result.run_id 关联被评的
  会话/评测 run（报告跳转详情），eval_run_id 关联批任务（runtime_gate/sample 为空），
  source 三值区分 eval_run / runtime_gate / runtime_sample 三个消费点（C5 同源）；
- 列类型口径对齐 agent_memory（0077）：全表 tenant_id UUID，updated_at 由仓储显式回写。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0079_eval_tables"
down_revision: str | None = "0078_conversation_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE eval_dataset (
            id              UUID         NOT NULL,
            tenant_id       UUID         NOT NULL,
            application_id  UUID         NOT NULL,
            name            VARCHAR(200) NOT NULL,
            description     TEXT         NOT NULL DEFAULT '',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_dataset PRIMARY KEY (id),
            CONSTRAINT fk_eval_dataset_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_dataset_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_eval_dataset_tenant_app "
        "ON eval_dataset (tenant_id, application_id)"
    )

    op.execute(
        """
        CREATE TABLE eval_case (
            id                  UUID    NOT NULL,
            tenant_id           UUID    NOT NULL,
            dataset_id          UUID    NOT NULL,
            input               JSONB   NOT NULL,
            expected            TEXT,
            expected_tool_calls JSONB,
            position            INT     NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_case PRIMARY KEY (id),
            CONSTRAINT fk_eval_case_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_case_dataset FOREIGN KEY (dataset_id)
                REFERENCES eval_dataset (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_eval_case_dataset ON eval_case (dataset_id, position)")

    op.execute(
        """
        CREATE TABLE eval_evaluator (
            id         UUID         NOT NULL,
            tenant_id  UUID         NOT NULL,
            name       VARCHAR(200) NOT NULL,
            type       VARCHAR(20)  NOT NULL,
            config     JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_evaluator PRIMARY KEY (id),
            CONSTRAINT fk_eval_evaluator_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT ck_eval_evaluator_type CHECK (type IN ('rule', 'llm_judge'))
        )
        """
    )
    op.execute("CREATE INDEX ix_eval_evaluator_tenant ON eval_evaluator (tenant_id)")

    op.execute(
        """
        CREATE TABLE eval_run (
            id              UUID         NOT NULL,
            tenant_id       UUID         NOT NULL,
            application_id  UUID         NOT NULL,
            graph_version   INT          NOT NULL,
            dataset_id      UUID         NOT NULL,
            evaluator_ids   JSONB        NOT NULL DEFAULT '[]'::jsonb,
            status          VARCHAR(20)  NOT NULL DEFAULT 'running',
            progress        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            usage           JSONB        NOT NULL DEFAULT '{}'::jsonb,
            error_message   TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_run PRIMARY KEY (id),
            CONSTRAINT fk_eval_run_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_run_application FOREIGN KEY (application_id)
                REFERENCES application (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_run_dataset FOREIGN KEY (dataset_id)
                REFERENCES eval_dataset (id) ON DELETE CASCADE,
            CONSTRAINT ck_eval_run_status CHECK (status IN ('running', 'completed', 'error'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_eval_run_tenant_app "
        "ON eval_run (tenant_id, application_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE eval_result (
            id           UUID        NOT NULL,
            tenant_id    UUID        NOT NULL,
            eval_run_id  UUID,
            run_id       UUID,
            case_id      UUID,
            status       VARCHAR(20) NOT NULL,
            score        INT,
            reason       TEXT        NOT NULL DEFAULT '',
            judge_usage  JSONB,
            source       VARCHAR(20) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_result PRIMARY KEY (id),
            CONSTRAINT fk_eval_result_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_result_eval_run FOREIGN KEY (eval_run_id)
                REFERENCES eval_run (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_result_run FOREIGN KEY (run_id)
                REFERENCES run (id) ON DELETE CASCADE,
            CONSTRAINT fk_eval_result_case FOREIGN KEY (case_id)
                REFERENCES eval_case (id) ON DELETE CASCADE,
            CONSTRAINT ck_eval_result_status CHECK (status IN ('pass', 'fail', 'error')),
            CONSTRAINT ck_eval_result_source
                CHECK (source IN ('eval_run', 'runtime_gate', 'runtime_sample'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_eval_result_eval_run ON eval_result (eval_run_id, case_id)"
    )
    op.execute(
        "CREATE INDEX ix_eval_result_source "
        "ON eval_result (tenant_id, source, created_at)"
    )


def downgrade() -> None:
    for table in ("eval_result", "eval_run", "eval_evaluator", "eval_case", "eval_dataset"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
