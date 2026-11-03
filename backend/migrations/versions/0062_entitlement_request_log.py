"""0062 幂等请求去重：entitlement_request_log（request_id 唯一 + version）（P3-8）。

Revision ID: 0062_entitlement_request_log
Revises: 0061_resource_type_catalog
Create Date: 2026-11-03

设计要点：
- Idempotency-Key 语义（Stripe 风格）：先占位 processing，重放读 completed 行的
  result 原样返回首次结果；processing 行存在表示并发执行中，服务层回 409 VERSION_CONFLICT。
- version 为同键接管重试计数（failed → processing 时 +1），非权益行乐观锁。
- tenant_id 不建外键：运营去重日志不应阻塞租户删除，与审计表同策略。
- result JSONB 仅在 completed 时有值；payload 留存供排查与重放比对。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062_entitlement_request_log"
down_revision: str | None = "0061_resource_type_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "entitlement_request_log"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_TABLE} (
            id UUID PRIMARY KEY,
            request_id VARCHAR(128) NOT NULL,
            tenant_id UUID NOT NULL,
            action VARCHAR(16) NOT NULL DEFAULT 'batch',
            status VARCHAR(16) NOT NULL DEFAULT 'processing',
            version INTEGER NOT NULL DEFAULT 1,
            payload JSONB NOT NULL,
            result JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            CONSTRAINT ck_entitlement_request_log_status
                CHECK (status IN ('processing', 'completed', 'failed'))
        )
        """
    )
    op.execute(f"CREATE UNIQUE INDEX ux_{_TABLE}_request_id ON {_TABLE} (request_id)")
    op.execute(f"CREATE INDEX ix_{_TABLE}_created ON {_TABLE} (created_at)")
    op.execute(
        f"COMMENT ON TABLE {_TABLE} IS "
        "'权益批量写幂等去重（P3-8）：同 Idempotency-Key 重放返回首次结果，processing 冲突 409'"
    )
    for col, comment in [
        ("request_id", "客户端 Idempotency-Key，唯一"),
        ("action", "去重范围：batch（套餐/purge 暂未纳入）"),
        ("status", "processing/completed/failed 三态"),
        ("version", "同键接管重试计数，failed→processing 时 +1"),
        ("payload", "归一化请求体 JSON，排查用"),
        ("result", "首次执行结果 JSON，completed 后重放原样返回"),
    ]:
        op.execute(f"COMMENT ON COLUMN {_TABLE}.{col} IS '{comment}'")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
