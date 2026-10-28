"""Workflow 节点实现：Start / LLM / Tool / End。

关键约束：``LLMNode`` 内部不允许起 FunctionCalling 主循环——图里的 Tool 节点就是
显式编排，避免"图里 LLM 隐式调图外工具"的混乱。
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.application.rag_utils import apply_rag_to_prompt
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.engine.context import AgentRunContext
from internal.engine.llm import LLMClient
from internal.engine.prompt import render_template
from internal.engine.tools import Tool, ToolExecutionError, build_tools
from internal.engine.workflow.context import WorkflowContext
from internal.infrastructure.observability.metrics import TOOL_CALLS, TOOL_DURATION

logger = logging.getLogger(__name__)


def _tenant_label(tenant_id: UUID | None) -> str:
    if tenant_id is None or tenant_id == PLATFORM_TENANT_ID:
        return "platform"
    return tenant_id.hex[:8]


class WorkflowNode(ABC):
    """运行期节点抽象。"""

    def __init__(self, node_id: str, data: dict[str, Any] | None) -> None:
        self.node_id = node_id
        self.data: dict[str, Any] = data or {}

    @abstractmethod
    async def execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        """返回该节点的输出 dict，会被写入 ``ctx.node_outputs[node_id]``。"""


class StartNode(WorkflowNode):
    """直接回显全局入参；variables 校验由 executor 统一负责。"""

    async def execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        return dict(ctx.global_inputs)


class LLMNode(WorkflowNode):
    """渲染 system/user prompt → 调 LLM（不带 tools）→ 返回 {output, usage, model}。"""

    def __init__(
        self,
        node_id: str,
        data: dict[str, Any] | None,
        llm_factory: Callable[[dict[str, Any]], LLMClient],
    ) -> None:
        super().__init__(node_id, data)
        self._llm_factory = llm_factory

    async def execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        node_outputs = ctx.node_outputs
        variables: dict[str, Any] = {
            **ctx.global_inputs,
            "tenant_id": str(ctx.tenant_id or ""),
        }

        system_prompt = render_template(
            str(self.data.get("system_prompt_tpl") or ""),
            variables,
            node_outputs,
        )
        user_prompt = render_template(
            str(self.data.get("user_prompt_tpl") or ""),
            variables,
            node_outputs,
        )
        if not user_prompt.strip():
            raise ValidationError(f"LLM 节点 {self.node_id} 的 user_prompt_tpl 为空")

        retrieval_cfg = self.data.get("retrieval") or {}
        if retrieval_cfg.get("enabled") and ctx.uow is not None and ctx.request_context is not None:
            system_prompt = await apply_rag_to_prompt(
                system_prompt=system_prompt,
                retrieval_cfg=retrieval_cfg if isinstance(retrieval_cfg, dict) else {},
                query=user_prompt,
                uow=ctx.uow,
                context=ctx.request_context,
            )

        messages: list[dict[str, Any]] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        llm = self._llm_factory(self.data)
        agent_ctx: AgentRunContext = ctx.as_agent_context()
        response = await llm.chat(
            messages=messages,
            temperature=self.data.get("temperature"),
            max_tokens=self.data.get("max_tokens"),
            context=agent_ctx,
        )
        return {
            "output": response.content,
            "model": response.model,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }


class ToolNode(WorkflowNode):
    """从 tools 表加载工具实体，渲染 arguments_tpl 后调用。"""

    async def execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        if ctx.uow is None:
            raise ValidationError("ToolNode 需要 UoW 注入")
        tool_id_raw = self.data.get("tool_id")
        if not tool_id_raw:
            raise ValidationError(f"Tool 节点 {self.node_id} 未配置 tool_id")
        try:
            tool_id = UUID(str(tool_id_raw))
        except ValueError as exc:
            raise ValidationError(f"Tool 节点 {self.node_id} 的 tool_id 非法") from exc

        entity = ctx.uow.tools.get(tool_id)
        if entity is None or not entity.is_enabled:
            raise NotFoundError(f"工具 {tool_id} 不存在或已停用")

        # 工具实体加载后立即 commit，释放 DB 连接；后续 tool.invoke 是 HTTP 调用
        try:
            ctx.uow.commit()
        except Exception:  # noqa: BLE001 - 读阶段 commit 失败不影响后续
            logger.debug("tool node uow commit failed", exc_info=True)

        runtime_tools = build_tools([entity])
        if not runtime_tools:
            raise NotFoundError(f"工具 {entity.name} 已停用")
        tool: Tool = runtime_tools[0]

        arguments_tpl = self.data.get("arguments_tpl") or {}
        if not isinstance(arguments_tpl, dict):
            raise ValidationError(f"Tool 节点 {self.node_id} 的 arguments_tpl 必须为对象")

        variables: dict[str, Any] = {
            **ctx.global_inputs,
            "tenant_id": str(ctx.tenant_id or ""),
        }
        arguments = {
            key: render_template(str(value), variables, ctx.node_outputs)
            for key, value in arguments_tpl.items()
        }

        started = time.perf_counter()
        tenant = _tenant_label(ctx.tenant_id)
        tool_status = "success"
        try:
            content = await tool.invoke(arguments, ctx.as_agent_context())
        except ToolExecutionError as exc:
            tool_status = "tool_error"
            raise ValidationError(f"工具 {entity.name} 执行失败：{exc.message}") from exc
        except Exception:
            tool_status = "unexpected_error"
            raise
        finally:
            duration = time.perf_counter() - started
            TOOL_DURATION.labels(tenant=tenant, tool=entity.name, status=tool_status).observe(duration)
            TOOL_CALLS.labels(tenant=tenant, tool=entity.name, status=tool_status).inc()

        return {"output": content}


class EndNode(WorkflowNode):
    """渲染 output_tpl 作为整图最终 outputs；executor 会用它的输出作为最终结果。"""

    async def execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        output_tpl = self.data.get("output_tpl") or {}
        if not isinstance(output_tpl, dict):
            raise ValidationError("End 节点 output_tpl 必须为对象")
        variables: dict[str, Any] = {
            **ctx.global_inputs,
            "tenant_id": str(ctx.tenant_id or ""),
        }
        return {
            key: render_template(str(value), variables, ctx.node_outputs)
            for key, value in output_tpl.items()
        }
