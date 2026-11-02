"""应用层端口：以 Protocol 反转应用层对外部装配能力的依赖。

RunnerFactory 抽象"如何装配一个 GraphRuntime"：具体实现位于组合根
（web/deps/graph.py 的 build_runner，允许同时 import application 与 infrastructure），
应用层只依赖本 Protocol，不再 import web，消除 application→web 反向依赖。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from internal.application.apps.application_service import ApplicationService
from internal.domain.graph.runtime import GraphRuntime


class RunnerFactory(Protocol):
    """装配 GraphRuntime 的工厂端口；参数形状与组合根 build_runner 一致。"""

    async def __call__(
        self,
        service: ApplicationService,
        uow: Any,
        context: Any,
        *,
        tenant_id: UUID,
        application_id: UUID,
        thread_id: str | None = None,
        run_id: UUID | None = None,
        current_user_id: UUID | None = None,
        actor_username: str | None = None,
        conversation_id: UUID | None = None,
        on_node_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> GraphRuntime:
        """加载 runtime graph 并组装服务注册表，返回可执行的 GraphRuntime。"""
