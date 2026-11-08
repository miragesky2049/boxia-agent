"""管理端长期记忆检索（M4 PRD F16.7）：租户×应用×用户维度排障列表。

平台管理员按应用排查沉淀的记忆内容与状态；只读，不提供管理端删除
（纠错路径=用户管理面自删，防止管理员误删用户隐私数据）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from web.deps.apps_services import make_agent_memory_repository
from web.deps.auth import require_platform_admin
from web.deps.db import UowDep

router = APIRouter(
    prefix="/agent-memories",
    tags=["agent-memories"],
    dependencies=[Depends(require_platform_admin)],
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "application_id": str(row["application_id"]),
        "user_id": str(row["user_id"]),
        "kind": row["kind"],
        "content": row["content"],
        "status": row["status"],
        "source_run_id": str(row["source_run_id"]) if row.get("source_run_id") else None,
        "hit_count": int(row.get("hit_count") or 0),
        "metadata": row.get("metadata") or {},
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


@router.get("")
def search_agent_memories(
    uow: UowDep,
    application_id: UUID = Query(..., description="应用 ID（必填，排障入口按应用聚合）"),
    tenant_id: UUID | None = Query(None, description="租户过滤；缺省=全部租户"),
    user_id: UUID | None = Query(None, description="用户过滤"),
    status: str = Query("active", pattern="^(active|archived|all)$"),
    keyword: str | None = Query(None, max_length=64, description="正文子串关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """分页返回符合条件的记忆行（时近倒序）与总数。"""
    items, total = make_agent_memory_repository(uow.session).search_for_admin(
        application_id=application_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {"items": [_serialize(row) for row in items], "total": total}
