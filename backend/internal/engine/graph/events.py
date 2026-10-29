"""事件总线：节点执行事件 + 订阅者。"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeExecutionEvent:
    """节点执行事件。"""

    run_id: UUID
    tenant_id: UUID
    application_id: UUID
    node_id: str
    node_type: str
    status: str  # started / success / error
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    token_usage: dict[str, int] | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


# 订阅者注册表
EventSubscriber = Callable[[NodeExecutionEvent], None]
SUBSCRIBERS: dict[str, list[EventSubscriber]] = defaultdict(list)


def subscribe(event_type: str = "node_execution"):
    """装饰器：订阅节点执行事件。"""

    def decorator(fn: EventSubscriber):
        SUBSCRIBERS[event_type].append(fn)
        return fn

    return decorator


def publish(event: NodeExecutionEvent, event_type: str = "node_execution") -> None:
    """发布事件，所有订阅者被调用。"""
    for subscriber in SUBSCRIBERS.get(event_type, []):
        try:
            subscriber(event)
        except Exception as e:
            logger.error(f"事件订阅者异常: {e}", exc_info=True)


# ========== 内置订阅者示例 ==========
@subscribe("node_execution")
def logging_subscriber(event: NodeExecutionEvent) -> None:
    """日志订阅者：记录节点执行。"""
    logger.info(
        f"[{event.status}] node={event.node_id} type={event.node_type} "
        f"duration={event.duration_ms}ms run={event.run_id}"
    )


@subscribe("node_execution")
def billing_subscriber(event: NodeExecutionEvent) -> None:
    """计费订阅者：LLM 节点记录 token 用量。"""
    if event.node_type == "llm" and event.status == "success" and event.token_usage:
        # TODO: 落 tenant_usage_ledger
        logger.debug(f"计费: tenant={event.tenant_id} tokens={event.token_usage}")


@subscribe("node_execution")
def audit_subscriber(event: NodeExecutionEvent) -> None:
    """审计订阅者：记录关键操作。"""
    if event.status == "error":
        # TODO: 落 audit_log
        logger.warning(f"节点失败: node={event.node_id} error={event.error}")
