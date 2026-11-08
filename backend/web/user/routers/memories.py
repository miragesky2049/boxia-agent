"""用户端长期记忆管理面（M4 PRD F16.6）：查看 / 删除本人智能体记忆。

作用域强制为登录态 tenant × 本人 user；application_id 必传（user×app 隔离）。
删除即物理删除（隐私口径），后续轮召回自然不再命中；单条删除作用域不匹配一律
按 404 处理（仓储 0 行），不区分"不存在"与"越权"，避免探测他人记忆 ID。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from internal.application.errors import NotFoundError, ValidationError
from web.deps.apps_services import make_agent_memory_repository
from web.deps.auth import UserAuthDep
from web.deps.db import UowDep

router = APIRouter(prefix="/memories", tags=["user-memories"])

# 抽屉单页返回上限：活跃容量默认 200、防御上限 2000，200 条足够 UI 展示与全选清空
MAX_VISIBLE_MEMORIES = 200


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    updated_at = row.get("updated_at")
    return {
        "memory_id": str(row["id"]),
        "kind": row["kind"],
        "content": row["content"],
        "updated_at": updated_at.isoformat() if updated_at else None,
        "hit_count": int(row.get("hit_count") or 0),
    }


@router.get("")
def list_memories(
    principal: UserAuthDep,
    uow: UowDep,
    application_id: UUID = Query(..., description="应用 ID（user×app 作用域）"),
) -> dict:
    """返回当前用户在该应用下的活跃记忆（时近倒序）与总数。"""
    repo = make_agent_memory_repository(uow.session)
    items = repo.list_active(
        tenant_id=principal.tenant_id,
        application_id=application_id,
        user_id=principal.user_id,
        limit=MAX_VISIBLE_MEMORIES,
    )
    total = repo.count_active(
        tenant_id=principal.tenant_id,
        application_id=application_id,
        user_id=principal.user_id,
    )
    return {"items": [_serialize(row) for row in items], "total": total}


@router.delete("/{memory_id}")
def delete_memory(
    principal: UserAuthDep,
    uow: UowDep,
    memory_id: UUID,
    application_id: UUID = Query(..., description="应用 ID（作用域校验）"),
) -> dict:
    """删除单条记忆；作用域不匹配（他人/他租户/他应用）统一 404。"""
    deleted = make_agent_memory_repository(uow.session).delete_scoped(
        memory_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        application_id=application_id,
    )
    if not deleted:
        raise NotFoundError("记忆不存在")
    uow.commit()
    return {"deleted": 1}


@router.delete("")
def clear_memories(
    principal: UserAuthDep,
    uow: UowDep,
    application_id: UUID = Query(..., description="应用 ID（user×app 作用域）"),
    confirm: bool = Query(False, description="清空确认位，必须为 true"),
) -> dict:
    """清空当前 user×app 全部记忆（物理删除，含已归档）；未带 confirm 拒绝。"""
    if not confirm:
        raise ValidationError("清空记忆需携带 confirm=true")
    deleted = make_agent_memory_repository(uow.session).delete_by_scope(
        tenant_id=principal.tenant_id,
        application_id=application_id,
        user_id=principal.user_id,
    )
    uow.commit()
    return {"deleted": deleted}
