"""用户端应用列表：当前租户已开通的产品级应用 + 租户自建应用。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text

from web.deps.auth import UserAuthDep
from web.deps.db import UowDep

router = APIRouter(prefix="/agents", tags=["user-agents"])


def _visible_apps(session: Any, tenant_id: UUID, keyword: str | None) -> list[dict]:
    """当前用户可见应用 = 已开通的产品级实例 + 本租户自建应用（owner_type=tenant）。"""
    params: dict[str, Any] = {"tid": str(tenant_id)}
    kw_clause = ""
    if keyword:
        kw_clause = " AND a.name ILIKE :kw"
        params["kw"] = f"%{keyword}%"

    rows = session.execute(
        text(
            f"""
            SELECT DISTINCT a.id, a.name, a.avatar_url, a.description, a.is_enabled
            FROM application a
            WHERE a.is_enabled = true
              AND (
                a.owner_type = 'tenant' AND a.owner_id = :tid
                OR a.id IN (
                    SELECT application_id FROM tenant_application_instance
                    WHERE tenant_id = :tid AND status = 'active'
                )
              )
              {kw_clause}
            ORDER BY a.updated_at DESC
            """
        ),
        params,
    ).all()
    return [
        {
            "id": str(r._mapping["id"]),
            "name": r._mapping["name"],
            "avatar_url": r._mapping["avatar_url"] or "",
            "description": r._mapping["description"] or "",
            "is_enabled": r._mapping["is_enabled"],
        }
        for r in rows
    ]


@router.get("")
def list_agents(
    principal: UserAuthDep,
    uow: UowDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=64),
) -> dict:
    """分页返回当前用户可见的应用卡片列表。"""
    items = _visible_apps(uow.session, principal.tenant_id, keyword)
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{agent_id}")
def get_agent(
    agent_id: UUID,
    principal: UserAuthDep,
    uow: UowDep,
) -> dict:
    """返回单个应用详情（用户端运行前拉取元信息）。"""
    items = _visible_apps(uow.session, principal.tenant_id, None)
    target = next((item for item in items if item["id"] == str(agent_id)), None)
    if target is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("应用不存在或未开通")
    return {**target, "config": {}, "skills": [], "tools": [], "components": [], "prompts": []}
