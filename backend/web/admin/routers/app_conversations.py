"""平台应用会话管理接口：会话列表 / 消息列表 / 删除。

会话由用户端 chat 在租户子域名下创建，这里供平台管理员按应用排查多轮对话。
租户默认取调用方身份，允许显式传 tenant_id（平台管理员可跨租户排查）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from internal.application.errors import ValidationError
from web.deps.apps_services import make_conversation_admin_service
from web.deps.auth import PlatformAdminDep, require_platform_admin
from web.deps.db import UowDep

router = APIRouter(
    prefix="/apps",
    tags=["app-conversations"],
    dependencies=[Depends(require_platform_admin)],
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _resolve_tenant(principal: PlatformAdminDep, tenant_id: UUID | None) -> UUID:
    """会话排查的租户作用域：显式参数优先，否则用调用方所属租户。"""
    if tenant_id is not None:
        return tenant_id
    if principal.tenant_id is None:
        raise ValidationError("无法识别租户")
    return principal.tenant_id


def _conversation_to_dict(row: dict) -> dict:
    return {
        "conversation_id": str(row["id"]),
        "application_id": str(row["application_id"]),
        "user_id": str(row["user_id"]),
        "username": row.get("username") or "",
        "display_name": row.get("display_name") or "",
        "title": row.get("title") or "",
        # channel=debug 为画布试运行会话，归属管理员账号
        "channel": row.get("channel") or "api",
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _message_to_dict(row: dict) -> dict:
    return {
        "message_id": str(row["id"]),
        "conversation_id": str(row["conversation_id"]),
        "role": row.get("role") or "user",
        "content": row.get("content") or "",
        "tool_calls": row.get("tool_calls"),
        "tool_call_id": row.get("tool_call_id"),
        "tool_name": row.get("tool_name"),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "metadata": row.get("metadata") or {},
        "created_at": _iso(row.get("created_at")),
    }


@router.get("/{application_id}/conversations")
def list_app_conversations(
    application_id: UUID,
    uow: UowDep,
    principal: PlatformAdminDep,
    tenant_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """列出应用下的会话（按最近活跃倒序，含所属用户）。"""
    scope_tenant = _resolve_tenant(principal, tenant_id)
    rows = make_conversation_admin_service(uow).list_app_conversations(
        tenant_id=scope_tenant,
        application_id=application_id,
        limit=limit,
        offset=offset,
    )
    return [_conversation_to_dict(row) for row in rows]


@router.get("/conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: UUID,
    uow: UowDep,
    principal: PlatformAdminDep,
    tenant_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    """拉取会话历史消息（升序）。"""
    scope_tenant = _resolve_tenant(principal, tenant_id)
    rows = make_conversation_admin_service(uow).list_messages(
        conversation_id=conversation_id,
        tenant_id=scope_tenant,
        limit=limit,
    )
    return [_message_to_dict(row) for row in rows]


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    uow: UowDep,
    principal: PlatformAdminDep,
    tenant_id: UUID | None = Query(None),
) -> dict:
    """删除会话；该会话下的消息由外键 ON DELETE CASCADE 一并清理。"""
    scope_tenant = _resolve_tenant(principal, tenant_id)
    make_conversation_admin_service(uow).delete_conversation(
        conversation_id=conversation_id,
        tenant_id=scope_tenant,
    )
    return {"ok": True}


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
def delete_conversation_message(
    conversation_id: UUID,
    message_id: UUID,
    uow: UowDep,
    principal: PlatformAdminDep,
    tenant_id: UUID | None = Query(None),
) -> dict:
    """删除会话内单条消息。"""
    scope_tenant = _resolve_tenant(principal, tenant_id)
    make_conversation_admin_service(uow).delete_message(
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=scope_tenant,
    )
    return {"ok": True}
