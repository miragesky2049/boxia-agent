"""DAG 调度器：拓扑分层、同层并行、节点超时、状态机。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from internal.application.errors import ValidationError
from internal.domain.entity.request_context import RequestContext
from internal.engine.llm import LLMClient
from internal.engine.workflow.context import WorkflowContext
from internal.engine.workflow.registry import build_node
from internal.engine.workflow.validator import (
    GraphValidationError,
    topological_layers,
    validate_graph,
)

logger = logging.getLogger(__name__)

DEFAULT_NODE_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class NodeState:
    """单个节点的执行状态；前端画布试运行时按此高亮。"""

    node_id: str
    type: str
    status: str  # pending / running / success / error
    duration_ms: int = 0
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class WorkflowRunResult:
    """整图运行结果。"""

    run_id: str
    outputs: dict[str, Any]
    node_states: list[NodeState]
    usage: dict[str, int]
    finish_reason: str  # success / error


class WorkflowExecutor:
    """同步 DAG 执行器：分层调度、同层 gather、失败即中断。"""

    def __init__(
        self,
        llm_factory: Callable[[dict[str, Any]], LLMClient],
        node_timeout_seconds: float = DEFAULT_NODE_TIMEOUT_SECONDS,
        event_callback: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._node_timeout = node_timeout_seconds
        self._event_callback = event_callback

    async def run(
        self,
        *,
        workflow_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
        graph: dict[str, Any],
        global_inputs: dict[str, Any],
        uow: Any = None,
        request_context: RequestContext | None = None,
    ) -> WorkflowRunResult:
        """执行整图；任一节点失败则 finish_reason=error 并返回已完成节点状态。"""
        try:
            validate_graph(graph)
        except GraphValidationError as exc:
            raise ValidationError(f"图校验失败：{exc.message}") from exc

        variables = graph.get("variables") or []
        self._validate_inputs(variables, global_inputs)

        ctx = WorkflowContext(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            user_id=user_id,
            global_inputs=global_inputs,
            uow=uow,
            request_context=request_context,
        )

        node_type_by_id: dict[str, str] = {
            node["id"]: str(node.get("type") or "") for node in graph.get("nodes") or []
        }
        data_by_id: dict[str, dict[str, Any]] = {
            node["id"]: dict(node.get("data") or {}) for node in graph.get("nodes") or []
        }

        states: dict[str, NodeState] = {
            node_id: NodeState(node_id=node_id, type=node_type, status="pending")
            for node_id, node_type in node_type_by_id.items()
        }
        usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        layers = topological_layers(graph)
        outputs: dict[str, Any] = {}
        finish_reason = "success"

        try:
            for layer in layers:
                for node_id in layer:
                    await self._emit(
                        "node_start",
                        {
                            "node_id": node_id,
                            "type": node_type_by_id[node_id],
                        },
                    )
                results = await asyncio.gather(
                    *(
                        self._run_one(node_id, node_type_by_id[node_id], data_by_id[node_id], ctx)
                        for node_id in layer
                    ),
                    return_exceptions=True,
                )
                for node_id, result in zip(layer, results):
                    if isinstance(result, Exception):
                        finish_reason = "error"
                        states[node_id] = NodeState(
                            node_id=node_id,
                            type=node_type_by_id[node_id],
                            status="error",
                            error=str(result),
                        )
                        await self._emit(
                            "node_end",
                            {
                                "node_id": node_id,
                                "type": node_type_by_id[node_id],
                                "status": "error",
                                "error": str(result),
                            },
                        )
                        raise result
                    output, duration_ms = result
                    states[node_id] = NodeState(
                        node_id=node_id,
                        type=node_type_by_id[node_id],
                        status="success",
                        duration_ms=duration_ms,
                        output=output,
                    )
                    await self._emit(
                        "node_end",
                        {
                            "node_id": node_id,
                            "type": node_type_by_id[node_id],
                            "status": "success",
                            "duration_ms": duration_ms,
                            "output": output,
                        },
                    )
                    if node_type_by_id[node_id] == "llm":
                        usage["prompt_tokens"] += int(output.get("prompt_tokens") or 0)
                        usage["completion_tokens"] += int(output.get("completion_tokens") or 0)
                        usage["total_tokens"] += int(output.get("total_tokens") or 0)
                    if node_type_by_id[node_id] == "end":
                        outputs = output
        except Exception as exc:  # noqa: BLE001 - 兜底中断，把未跑节点标 pending
            logger.warning("workflow run failed workflow=%s err=%s", workflow_id, exc)
            for node_id, state in states.items():
                if state.status == "pending":
                    states[node_id] = NodeState(
                        node_id=node_id, type=state.type, status="pending"
                    )

        return WorkflowRunResult(
            run_id=ctx.run_id,
            outputs=outputs,
            node_states=list(states.values()),
            usage=usage,
            finish_reason=finish_reason,
        )

    async def _run_one(
        self,
        node_id: str,
        node_type: str,
        data: dict[str, Any],
        ctx: WorkflowContext,
    ) -> tuple[dict[str, Any], int]:
        """执行单个节点并返回 (output, duration_ms)。"""
        node = build_node(node_id, node_type, data, self._llm_factory)
        started = time.perf_counter()
        try:
            output = await asyncio.wait_for(node.execute(ctx), timeout=self._node_timeout)
        except TimeoutError as exc:
            raise ValidationError(
                f"节点 {node_id} 执行超时（>{self._node_timeout}s）"
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        ctx.record_output(node_id, output)
        return output, duration_ms

    async def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """外抛运行事件；回调为 None 时静默跳过。"""
        if self._event_callback is None:
            return
        try:
            result = self._event_callback(event, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 - 回调异常不能影响主流程
            logger.warning("workflow event callback failed event=%s", event, exc_info=True)

    @staticmethod
    def _validate_inputs(
        variables: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> None:
        """按 graph.variables 校验必填入参。"""
        for variable in variables or []:
            key = variable.get("key")
            if not key:
                continue
            required = bool(variable.get("required"))
            if required and inputs.get(key) in (None, ""):
                raise ValidationError(f"缺少必填入参：{key}")
