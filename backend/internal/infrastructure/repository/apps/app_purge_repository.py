"""平台应用物理删除的级联清理仓储（仅裸 SQL，与调用方共享事务）。

删除一个平台应用涉及三类表（外键真相以 migrations 为准）：

1. 数据库外键 CASCADE 自动覆盖：application_graph、application_graph_version、
   tenant_application_instance、tenant_application_config、
   application_visibility_departments/users、conversation/message——
   最后 DELETE application 行时统一触发。
2. RESTRICT 阻塞点，必须先显式删除：run（workflow_id→application RESTRICT；
   删 run 级联清 run_node_execution，并使 message.run_id SET NULL）、
   application_apply（application_id RESTRICT）。
3. 无外键裸列/多态关联，必须手工按 application_id 或类型+ID 清理，否则留下孤儿：
   application_user_variable、tenant_usage_ledger、event_webhook、
   resource_grants(resource_type='app')、entitlement_plan_item(object_type='app')。

顺序约束固化在 purge_business_data 中；新增引用 application 的数据表时，
必须同步评估是否要把该表加入本类的清理与 snapshot 清单。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# 删前快照计数：键为审计 detail 中的逻辑名，值为计数 SQL（谓词已含 :aid）
_SNAPSHOT_SQL = """
    SELECT
        (SELECT count(*) FROM run WHERE workflow_id = :aid) AS runs,
        (SELECT count(*) FROM run_node_execution ne
            JOIN run r ON r.id = ne.execute_id WHERE r.workflow_id = :aid)
            AS run_node_executions,
        (SELECT count(*) FROM application_apply WHERE application_id = :aid)
            AS application_apply,
        (SELECT count(*) FROM tenant_application_instance
            WHERE application_id = :aid) AS app_instances,
        (SELECT count(*) FROM conversation WHERE application_id = :aid) AS conversations,
        (SELECT count(*) FROM message WHERE application_id = :aid) AS messages,
        (SELECT count(*) FROM tenant_usage_ledger WHERE application_id = :aid)
            AS usage_ledger,
        (SELECT count(*) FROM event_webhook WHERE application_id = :aid) AS webhooks,
        (SELECT count(*) FROM application_user_variable
            WHERE application_id = :aid) AS user_variables,
        (SELECT count(*) FROM resource_grants
            WHERE resource_type = 'app' AND resource_id = :aid) AS resource_grants,
        (SELECT count(*) FROM entitlement_plan_item
            WHERE object_type = 'app' AND object_id = :aid) AS plan_items
"""

# 业务数据清理步骤，顺序不可调换：
# - 无 FK 裸列与多态表先清，避免遗留孤儿；
# - run.workflow_id 对 application RESTRICT，run 必须先于 application（级联 run_node_execution）；
# - application_apply 为 RESTRICT，必须先于 application；
# - message 末位兜底（正常已随 conversation CASCADE）。
_PURGE_STEPS: tuple[tuple[str, str], ...] = (
    (
        "application_user_variable",
        "DELETE FROM application_user_variable WHERE application_id = :aid",
    ),
    (
        "resource_grants",
        "DELETE FROM resource_grants WHERE resource_type = 'app' AND resource_id = :aid",
    ),
    (
        "entitlement_plan_item",
        "DELETE FROM entitlement_plan_item WHERE object_type = 'app' AND object_id = :aid",
    ),
    (
        "tenant_usage_ledger",
        "DELETE FROM tenant_usage_ledger WHERE application_id = :aid",
    ),
    ("event_webhook", "DELETE FROM event_webhook WHERE application_id = :aid"),
    ("run", "DELETE FROM run WHERE workflow_id = :aid"),
    ("application_apply", "DELETE FROM application_apply WHERE application_id = :aid"),
    ("message", "DELETE FROM message WHERE application_id = :aid"),
)


class PostgresAppPurgeRepository:
    """在调用方事务内执行平台应用关联数据的物理清理。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def configure_timeouts(
        self, *, statement_timeout: str = "60s", lock_timeout: str = "5s"
    ) -> None:
        """放宽本事务语句/锁超时（SET LOCAL 仅当前事务生效）。

        大应用删除涉及多条 DELETE，默认 statement_timeout=5s 不够；
        超时值为代码内常量，不接受外部输入，直接内联无注入风险。
        """
        self._session.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout}'"))
        self._session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))

    def snapshot(self, application_id: UUID) -> dict[str, int]:
        """删除前对关键表做 count(*)，供审计留痕。"""
        row = self._session.execute(text(_SNAPSHOT_SQL), {"aid": application_id}).one()
        return {key: int(value) for key, value in row._mapping.items()}

    def purge_business_data(self, application_id: UUID) -> dict[str, int]:
        """按固定顺序删除应用业务数据，返回 {表名: 删除行数}。

        不在此处提交事务，由调用方统一 commit/rollback。
        """
        counts: dict[str, int] = {}
        for table, sql in _PURGE_STEPS:
            result = self._session.execute(text(sql), {"aid": application_id})
            counts[table] = int(result.rowcount)
        return counts

    def delete_application_row(self, application_id: UUID) -> int:
        """删除 application 行并触发全部 CASCADE；返回删除行数（0 表示应用不存在）。"""
        result = self._session.execute(
            text("DELETE FROM application WHERE id = :aid"),
            {"aid": application_id},
        )
        return int(result.rowcount)
