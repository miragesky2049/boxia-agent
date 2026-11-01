"""平台应用会话管理接口：会话列表 / 消息列表 / 删除。

会话由用户端 chat 在租户子域名下创建，这里供平台管理员按应用排查多轮对话。
租户默认取调用方身份，允许显式传 tenant_id（平台管理员可跨租户排查）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from internal.application.errors import NotFoundError, ValidationError
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import MessageRepository
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


def _load_conversation_in_scope(
    repo: ConversationRepository,
    conversation_id: UUID,
    tenant_id: UUID,
) -> dict:
    """按租户校验会话归属，查不到或跨租户统一按不存在处理，避免暴露他人会话。"""
    row = repo.get_conversation(conversation_id)
    if row is None or row.get("tenant_id") != tenant_id:
        raise NotFoundError("会话不存在")
    return row


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
    rows = ConversationRepository(uow.session).list_conversations_by_application(
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
    _load_conversation_in_scope(
        ConversationRepository(uow.session), conversation_id, scope_tenant,
    )
    rows = MessageRepository(uow.session).list_messages_by_conversation(
        conversation_id, limit=limit,
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
    repo = ConversationRepository(uow.session)
    _load_conversation_in_scope(repo, conversation_id, scope_tenant)
    repo.delete_conversation(conversation_id)
    uow.commit()
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
    _load_conversation_in_scope(
        ConversationRepository(uow.session), conversation_id, scope_tenant,
    )
    msg_repo = MessageRepository(uow.session)
    row = msg_repo.get_message(message_id)
    if row is None or row.get("conversation_id") != conversation_id:
        raise NotFoundError("消息不存在")
    msg_repo.delete_message(message_id)
    uow.commit()
    return {"ok": True}
