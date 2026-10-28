"""工作流运行用例：加载 graph → 调 DAG 执行器 → 返回 outputs 与节点状态。"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

from internal.application.errors import ForbiddenError, NotFoundError
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.engine.llm import LLMClient, OpenAICompatLLMClient
from internal.engine.workflow.executor import WorkflowExecutor, WorkflowRunResult

logger = logging.getLogger(__name__)


class WorkflowRunService:
    """用户端工作流运行用例；可见性由 UserScopedUow 的 workflows 仓储保证。"""

    def __init__(
        self,
        uow: UnitOfWork,
        context: RequestContext,
        llm_factory: Callable[[dict[str, Any]], LLMClient] | None = None,
    ) -> None:
        self._uow = uow
        self._context = context
        self._llm_factory = llm_factory

    async def run(
        self,
        *,
        workflow_id: UUID,
        inputs: dict[str, Any],
        user_id: UUID,
        event_callback: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> WorkflowRunResult:
        """同步执行一次工作流；event_callback 非空时通过它外抛节点事件（SSE 用）。"""
        if self._context.is_platform:
            raise ForbiddenError("用户端仅支持通过租户子域名访问")

        workflow = self._uow.workflows.get(workflow_id)
        if workflow is None or not workflow.is_enabled:
            raise NotFoundError("工作流不存在或未对当前用户开放")

        # 加载完成后立即 commit，把连接归还连接池；
        # 运行期 ToolNode 会 autobegin 新的短事务做工具查询，用完即释放。
        try:
            self._uow.commit()
        except Exception:  # noqa: BLE001
            logger.debug("uow commit after load failed", exc_info=True)

        executor = WorkflowExecutor(
            llm_factory=self._build_llm_factory(),
            event_callback=event_callback,
        )
        return await executor.run(
            workflow_id=workflow.id,
            tenant_id=self._context.tenant_id,
            user_id=user_id,
            graph=dict(workflow.graph or {}),
            global_inputs=dict(inputs or {}),
            uow=self._uow,
            request_context=self._context,
        )

    def _build_llm_factory(self) -> Callable[[dict[str, Any]], LLMClient]:
        """按节点 data 里的 model_id 构造 LLM 客户端；测试可注入 mock。"""
        if self._llm_factory is not None:
            return self._llm_factory

        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        api_key = settings.llm_api_key.get_secret_value()
        base_url = settings.llm_base_url
        timeout = settings.llm_timeout_seconds
        default_model = settings.llm_model_id

        def _factory(node_data: dict[str, Any]) -> LLMClient:
            model = str(node_data.get("model_id") or default_model)
            return OpenAICompatLLMClient(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout_seconds=timeout,
                default_temperature=float(node_data.get("temperature") or settings.llm_temperature),
                default_max_tokens=int(node_data.get("max_tokens") or settings.llm_max_tokens),
            )

        return _factory
