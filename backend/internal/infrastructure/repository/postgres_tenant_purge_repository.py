"""租户物理删除的级联清理仓储（仅裸 SQL，与调用方共享事务）。

删除一个租户涉及三类表（外键真相以 migrations 为准）：

1. 数据库外键 CASCADE 自动覆盖：roles/role_permissions、users/user_roles/
   user_refresh_tokens、departments、user_employments、hr_dictionaries、
   mgmt_units 系列、resource_grants(RBAC)、tenant_application_instance、
   tenant_resource_entitlement、tenant_application_config、tenant_settings、
   conversation/message 等——最后 DELETE tenants 行时统一触发。
2. RESTRICT 阻塞点，必须先显式删除：application_apply（tenant/application 双 RESTRICT）、
   documents（tenant RESTRICT）、audit_logs（NOT NULL 列 + 删 tenants 违约）。
3. 无外键裸列，必须手工按 tenant_id/owner_id 清理，否则留下孤儿：
   run（tenant_id 无 FK，workflow_id→application RESTRICT，必须先于 application 删除）、
   tenant_usage_ledger、event_webhook、entitlement_request_log、
   application_user_variable、租户多态所有的 application/resource。

顺序约束固化在 purge_business_data 中；新增带 tenant_id 的数据表时，
必须同步评估是否要把该表加入本类的清理与 snapshot 清单。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# 删前快照计数：键为审计 detail 中的逻辑名，值为计数 SQL（谓词已含 :tid）
_SNAPSHOT_SQL = """
    SELECT
        (SELECT count(*) FROM users WHERE tenant_id = :tid) AS users,
        (SELECT count(*) FROM roles WHERE tenant_id = :tid) AS roles,
        (SELECT count(*) FROM departments WHERE tenant_id = :tid) AS departments,
        (SELECT count(*) FROM hr_dictionaries WHERE tenant_id = :tid) AS hr_dictionaries,
        (SELECT count(*) FROM mgmt_units WHERE tenant_id = :tid) AS mgmt_units,
        (SELECT count(*) FROM documents WHERE tenant_id = :tid) AS documents,
        (SELECT count(*) FROM conversation WHERE tenant_id = :tid) AS conversations,
        (SELECT count(*) FROM message WHERE tenant_id = :tid) AS messages,
        (SELECT count(*) FROM run WHERE tenant_id = :tid) AS runs,
        (SELECT count(*) FROM application_apply WHERE tenant_id = :tid) AS application_apply,
        (SELECT count(*) FROM tenant_application_instance WHERE tenant_id = :tid) AS app_instances,
        (SELECT count(*) FROM tenant_resource_entitlement WHERE tenant_id = :tid) AS resource_entitlements,
        (SELECT count(*) FROM audit_logs WHERE tenant_id = :tid) AS audit_logs,
        (SELECT count(*) FROM application
            WHERE owner_type = 'tenant' AND owner_id = :tid) AS owned_applications,
        (SELECT count(*) FROM resource
            WHERE owner_type = 'tenant' AND owner_id = :tid) AS owned_resources
"""

# 业务数据清理步骤，顺序不可调换：
# - application_user_variable 无 FK，先于其应用本体删除；
# - run.workflow_id 对 application RESTRICT，run 必须先于 owned application；
# - application_apply/documents 为 RESTRICT，必须先于 application/tenants；
# - application/resource 仅删租户多态所有行，平台行（owner_type='platform'）绝不触碰；
# - message 末位兜底（正常已随 conversation CASCADE）。
_PURGE_STEPS: tuple[tuple[str, str], ...] = (
    (
        "application_user_variable",
        """
        DELETE FROM application_user_variable
        WHERE application_id IN (
            SELECT id FROM application
            WHERE owner_type = 'tenant' AND owner_id = :tid
        )
        """,
    ),
    ("run", "DELETE FROM run WHERE tenant_id = :tid"),
    ("tenant_usage_ledger", "DELETE FROM tenant_usage_ledger WHERE tenant_id = :tid"),
    ("event_webhook", "DELETE FROM event_webhook WHERE tenant_id = :tid"),
    ("entitlement_request_log", "DELETE FROM entitlement_request_log WHERE tenant_id = :tid"),
    ("application_apply", "DELETE FROM application_apply WHERE tenant_id = :tid"),
    ("document_chunks", "DELETE FROM document_chunks WHERE tenant_id = :tid"),
    ("documents", "DELETE FROM documents WHERE tenant_id = :tid"),
    (
        "application",
        "DELETE FROM application WHERE owner_type = 'tenant' AND owner_id = :tid",
    ),
    (
        "resource",
        "DELETE FROM resource WHERE owner_type = 'tenant' AND owner_id = :tid",
    ),
    ("message", "DELETE FROM message WHERE tenant_id = :tid"),
)


class PostgresTenantPurgeRepository:
    """在调用方事务内执行租户关联数据的物理清理。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def configure_timeouts(
        self, *, statement_timeout: str = "60s", lock_timeout: str = "5s"
    ) -> None:
        """放宽本事务语句/锁超时（SET LOCAL 仅当前事务生效）。

        大租户删除涉及多条 DELETE，默认 statement_timeout=5s 不够；
        超时值为代码内常量，不接受外部输入，直接内联无注入风险。
        """
        self._session.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout}'"))
        self._session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))

    def snapshot(self, tenant_id: UUID) -> dict[str, int]:
        """删除前对关键表做 count(*)，供审计留痕。"""
        row = self._session.execute(text(_SNAPSHOT_SQL), {"tid": tenant_id}).one()
        return {key: int(value) for key, value in row._mapping.items()}

    def purge_business_data(self, tenant_id: UUID) -> dict[str, int]:
        """按固定顺序删除租户业务数据，返回 {表名: 删除行数}。

        不在此处提交事务，由调用方统一 commit/rollback。
        """
        counts: dict[str, int] = {}
        for table, sql in _PURGE_STEPS:
            result = self._session.execute(text(sql), {"tid": tenant_id})
            counts[table] = int(result.rowcount)
        return counts

    def delete_audit_logs(self, tenant_id: UUID) -> int:
        """物理清除租户自身审计日志（平台侧删除审计须先写并 flush）。"""
        result = self._session.execute(
            text("DELETE FROM audit_logs WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        return int(result.rowcount)

    def delete_tenant_row(self, tenant_id: UUID) -> int:
        """删除 tenants 行并触发全部 CASCADE；返回删除行数（0 表示租户不存在）。"""
        result = self._session.execute(
            text("DELETE FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )
        return int(result.rowcount)
