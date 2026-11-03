"""P3-9 对账作业：扫描授权/权益三类漂移并写告警审计，只报告不自动清理。

口径与读侧对齐（D-3）：有效 = status IN (active, wait_effect) 且时间窗命中，
与 grant_filters.entitlement_active_exists 一致。平台租户自身的角色授权不参与
租户权益对账（授权对象是平台员工，非租户开通）。"权益指向已删除对象"的悬挂在
库内结构性不可能：tenant_resource_entitlement.resource_id 与
tenant_application_instance.application_id 均有 FK+CASCADE，删对象即连带清理
权益行；漂移只会出现在无 FK 的 resource_grants 侧，归入 orphan_grants。
app 类授权一律要求实例有效。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.application.audit import record_audit
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)

_SAMPLE_LIMIT = 20
_VALID_STATUS = "('active', 'wait_effect')"

_SQL_DANGLING_GRANTS = f"""
    SELECT g.id::text AS grant_id, g.tenant_id::text AS tenant_id,
           g.resource_type, g.resource_id::text AS resource_id, g.subject_type
    FROM resource_grants g
    JOIN resource r ON r.id = g.resource_id AND r.type = g.resource_type
    WHERE g.tenant_id <> :platform AND g.resource_type <> 'app'
      AND r.owner_type = 'platform'
      AND NOT EXISTS (
          SELECT 1 FROM tenant_resource_entitlement e
          WHERE e.tenant_id = g.tenant_id AND e.resource_id = g.resource_id
            AND e.status IN {_VALID_STATUS}
            AND (e.start_time IS NULL OR e.start_time <= NOW())
            AND (e.expire_time IS NULL OR e.expire_time > NOW())
      )
"""

_SQL_DANGLING_APP_GRANTS = f"""
    SELECT g.id::text AS grant_id, g.tenant_id::text AS tenant_id,
           g.resource_type, g.resource_id::text AS resource_id, g.subject_type
    FROM resource_grants g
    WHERE g.tenant_id <> :platform AND g.resource_type = 'app'
      AND EXISTS (SELECT 1 FROM application a WHERE a.id = g.resource_id)
      AND NOT EXISTS (
          SELECT 1 FROM tenant_application_instance i
          WHERE i.tenant_id = g.tenant_id AND i.application_id = g.resource_id
            AND i.status IN {_VALID_STATUS}
            AND (i.start_time IS NULL OR i.start_time <= NOW())
            AND (i.expire_time IS NULL OR i.expire_time > NOW())
      )
"""

_SQL_UNAPPROVED_GRANTS = """
    SELECT g.id::text AS grant_id, g.tenant_id::text AS tenant_id,
           g.resource_type, g.resource_id::text AS resource_id, r.review_status
    FROM resource_grants g
    JOIN resource r ON r.id = g.resource_id AND r.type = g.resource_type
    WHERE g.tenant_id <> :platform AND g.resource_type <> 'app'
      AND r.review_status <> 'approved'
"""

_SQL_ORPHAN_GRANTS = """
    SELECT g.id::text AS grant_id, g.tenant_id::text AS tenant_id,
           g.resource_type, g.resource_id::text AS resource_id
    FROM resource_grants g
    LEFT JOIN resource r ON r.id = g.resource_id AND r.type = g.resource_type
    LEFT JOIN application a ON a.id = g.resource_id AND g.resource_type = 'app'
    WHERE g.tenant_id <> :platform AND r.id IS NULL AND a.id IS NULL
"""

_SUGGESTION = (
    "dangling_grants：补开通权益或撤销授权行；unapproved_grants：完成资源审核或收回授权；"
    "orphan_grants：清理指向已删除对象的授权行"
)


def _count_and_sample(
    session: Session, sql: str, params: dict[str, Any]
) -> tuple[int, list[dict[str, Any]]]:
    """单类漂移的总数 + 封顶样本；样本含 LIMIT 截断，总数为全量。"""
    count = session.execute(text(f"SELECT count(*) FROM ({sql}) AS drift"), params).scalar_one()
    rows = (
        session.execute(
            text(f"{sql} LIMIT :sample_limit"), {**params, "sample_limit": _SAMPLE_LIMIT}
        )
        .mappings()
        .all()
    )
    return int(count), [dict(row) for row in rows]


def scan_drift(session: Session) -> dict[str, Any]:
    """扫描三类漂移，返回计数+封顶样本+清理建议的汇总（审计 detail 口径）。"""
    params = {"platform": PLATFORM_TENANT_ID}
    dangling_resource_count, dangling_resource_rows = _count_and_sample(
        session, _SQL_DANGLING_GRANTS, params
    )
    dangling_app_count, dangling_app_rows = _count_and_sample(
        session, _SQL_DANGLING_APP_GRANTS, params
    )
    unapproved = _count_and_sample(session, _SQL_UNAPPROVED_GRANTS, params)
    orphan_grants = _count_and_sample(session, _SQL_ORPHAN_GRANTS, params)

    categories: dict[str, dict[str, Any]] = {
        "dangling_grants": {
            "count": dangling_resource_count + dangling_app_count,
            "samples": (dangling_resource_rows + dangling_app_rows)[:_SAMPLE_LIMIT],
        },
        "unapproved_grants": {"count": unapproved[0], "samples": unapproved[1]},
        "orphan_grants": {"count": orphan_grants[0], "samples": orphan_grants[1]},
    }
    return {
        "total": sum(int(item["count"]) for item in categories.values()),
        **categories,
        "suggestion": _SUGGESTION,
    }


@celery_app.task(name="entitlement.reconcile")
def reconcile_task() -> dict[str, Any]:
    """定时：授权/权益漂移对账，汇总写审计（action=entitlement.reconcile）供运营人工处置。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        summary = scan_drift(uow.session)
        audit_id = record_audit(
            uow,
            "entitlement.reconcile",
            actor_username="system",
            resource_type="entitlement",
            detail=summary,
        )
        uow.commit()
    finally:
        uow.close()
    if summary["total"] > 0:
        logger.warning("权益对账发现 %s 条漂移，明细见审计 %s", summary["total"], audit_id)
    else:
        logger.info("权益对账完成，未发现漂移")
    return {**summary, "audit_id": str(audit_id)}
