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


class CanvasDebugRuntimeFactory(Protocol):
    """装配画布试运行 GraphRuntime 的工厂端口（组合根 web/deps/graph.py 实现）。

    与 RunnerFactory 的区别：试运行直接用前端传来的未保存 graph 装配
    ServiceRegistry + 调试变量，不加载已发布版本；on_node_event 为应用层
    编排（canvas_debug_service）的节点事件推送回调。
    """

    def __call__(
        self,
        *,
        graph: dict[str, Any],
        application_id: UUID,
        variables_application_id: UUID | None,
        run_id: UUID,
        conversation_id: UUID | None,
        thread_id: str | None,
        on_node_event: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> GraphRuntime:
        """按调试上下文组装 ServiceRegistry 与变量池，返回可执行的 GraphRuntime。"""
