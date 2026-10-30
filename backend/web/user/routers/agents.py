"""用户端应用列表：当前用户可见的应用（按数据可见范围收敛）。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text

from web.deps.auth import UserAuthDep
from web.deps.db import UowDep

router = APIRouter(prefix="/agents", tags=["user-agents"])


def _visible_apps(
    session: Any,
    tenant_id: UUID,
    user_id: UUID,
    keyword: str | None,
) -> list[dict]:
    """当前用户可见应用 = 已开通的产品级实例 + 本租户自建应用，再叠加 visibility_mode 过滤。

    - visibility_mode='all'：任意来源都可见；
    - visibility_mode='custom'：必须命中 application_visibility_users（直接白名单）
      或 application_visibility_departments（所在部门命中，include_subtree 时含子部门）。
    """
    params: dict[str, Any] = {"tid": str(tenant_id), "uid": str(user_id)}
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
              AND (
                a.visibility_mode = 'all'
                OR a.id IN (
                    SELECT application_id FROM application_visibility_users
                    WHERE user_id = :uid
                )
                OR a.id IN (
                    SELECT avd.application_id
                    FROM application_visibility_departments avd
                    JOIN user_employments ue ON ue.tenant_id = :tid
                    JOIN departments d ON d.id = ue.department_id AND d.tenant_id = :tid
                    WHERE ue.user_id = :uid
                      AND ue.is_current = true
                      AND avd.department_id = ue.department_id
                    UNION
                    SELECT avd.application_id
                    FROM application_visibility_departments avd
                    JOIN departments target_d ON target_d.id = avd.department_id
                    JOIN user_employments ue ON ue.tenant_id = :tid
                    JOIN departments d ON d.id = ue.department_id AND d.tenant_id = :tid
                    WHERE ue.user_id = :uid
                      AND ue.is_current = true
                      AND avd.include_subtree = true
                      AND d.path LIKE '/' || target_d.id::text || '/%'
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
    items = _visible_apps(uow.session, principal.tenant_id, principal.user_id, keyword)
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
    items = _visible_apps(uow.session, principal.tenant_id, principal.user_id, None)
    target = next((item for item in items if item["id"] == str(agent_id)), None)
    if target is None:
        from internal.application.errors import NotFoundError

        raise NotFoundError("应用不存在或未开通")
    return {**target, "config": {}, "skills": [], "tools": [], "components": [], "prompts": []}
