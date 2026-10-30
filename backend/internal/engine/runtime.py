"""GraphRuntime：包装 compiled graph，负责 invoke / run 持久化 / 节点执行明细 / webhook。

从老 GraphRunner 重构：
- 职责单一：编译 + 执行 + 记录
- 依赖通过 ServiceRegistry 注入（llm / http / subgraph_loader），不走 ContextVar
- 人审中断（human_task）本次 stub，后续迭代实现 interrupt + Command(resume)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.domain.canvas.convert import convert_canvas
from internal.domain.canvas.model import CanvasGraph
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import RuntimeEnv, ServiceRegistry
from internal.engine.checkpoint import get_checkpointer

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task] = set()
_UNSET = object()


class GraphInterrupted(Exception):
    """人审中断：本次迁移暂不抛出，预留类型给 chat_service.run_workflow 捕获。"""

    def __init__(self, interrupt_payload: dict[str, Any]) -> None:
        super().__init__("workflow waiting for approval")
        self.interrupt_payload = interrupt_payload


class GraphRuntime:
    """工作流运行时：编译画布 JSON 并执行。"""

    def __init__(
        self,
        canvas_json: dict[str, Any],
        services: ServiceRegistry | None = None,
        run_repo: Any = None,
        usage_repo: Any = None,
        audit_repo: Any = None,
        webhook_repo: Any = None,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        application_id: UUID | None = None,
        run_id: UUID | None = None,
        thread_id: str | None = None,
        actor_username: str | None = None,
        checkpointer: Any = _UNSET,
        on_node_event: Any = None,
    ):
        self.canvas_json = canvas_json
        self.services = services or ServiceRegistry()
        self.run_repo = run_repo
        self.usage_repo = usage_repo
        self.audit_repo = audit_repo
        self.webhook_repo = webhook_repo
        self.tenant_id = tenant_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
        self.user_id = user_id
        self.application_id = application_id or uuid.uuid4()
        self.run_id = run_id or uuid.uuid4()
        self.thread_id = thread_id or str(uuid.uuid4())
        self.actor_username = actor_username
        # checkpointer 默认 _UNSET 走 get_checkpointer；显式传 None 表示不挂 checkpointer
        self._checkpointer_override = checkpointer
        # 逐节点事件回调：async callable(event_type: str, payload: dict)
        self._on_node_event = on_node_event

        self._canvas: CanvasGraph | None = None
        self._compiled: Any = None
        self._node_types: dict[str, str] = {}

    async def _ensure_compiled(self) -> None:
        if self._compiled is not None:
            return

        self._canvas = convert_canvas(self.canvas_json)
        self._node_types = {n.id: n.type.value for n in self._canvas.nodes}

        env = RuntimeEnv(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            run_id=self.run_id,
            thread_id=self.thread_id,
            application_id=self.application_id,
        )

        if self._checkpointer_override is _UNSET:
            checkpointer = await get_checkpointer()
        else:
            checkpointer = self._checkpointer_override
        compiler = Compiler(services=self.services)
        self._compiled = compiler.compile(self._canvas, env, checkpointer=checkpointer)

    def _config(self) -> dict[str, Any]:
        # checkpointer=None 时不传 thread_id，否则 langgraph 报 "No checkpointer set"
        if self._checkpointer_override is None:
            return {}
        return {"configurable": {"thread_id": f"{self.tenant_id}:{self.thread_id}"}}

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行工作流，返回最终 output。人审中断本次不触发。"""
        started_at = time.time()
        await self._ensure_compiled()

        if self.run_repo is not None:
            try:
                self.run_repo.insert_run(
                    run_id=self.run_id,
                    tenant_id=self.tenant_id,
                    workflow_id=self.application_id,
                    graph_snapshot=self.canvas_json,
                    input_data=input_data,
                    thread_id=self.thread_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("写 run 记录失败")

        initial_state = {
            "input": input_data,
            "node_outputs": {},
            "globals": {},
            "env": {
                "tenant_id": str(self.tenant_id),
                "user_id": str(self.user_id) if self.user_id else None,
                "run_id": str(self.run_id),
                "thread_id": self.thread_id,
            },
            "output": {},
            "errors": {},
        }

        try:
            final_state_values = await self._stream_and_record(initial_state)

            if self._checkpointer_override is not None:
                # 有 checkpointer 时从持久化 state 读 output
                snapshot = await self._compiled.aget_state(self._config())
                output = snapshot.values.get("output", {}) if snapshot.values else {}
            else:
                # 无 checkpointer 时直接用流式结束时的 state
                output = (final_state_values or {}).get("output", {})

            duration_ms = int((time.time() - started_at) * 1000)

            if self.run_repo is not None:
                try:
                    self.run_repo.update_run_status(
                        self.run_id, execute_status="success", output=output
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("更新 run 状态失败")

            await self._notify_webhooks("run_finished", {
                "run_id": str(self.run_id),
                "tenant_id": str(self.tenant_id),
                "application_id": str(self.application_id),
                "thread_id": self.thread_id,
                "status": "success",
                "output": output,
                "duration_ms": duration_ms,
            })

            logger.info("运行完成: run=%s duration=%sms", self.run_id, duration_ms)
            return output

        except Exception as e:
            duration_ms = int((time.time() - started_at) * 1000)
            if self.run_repo is not None:
                try:
                    self.run_repo.update_run_status(
                        self.run_id, execute_status="error", error_message=str(e)
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("更新 run 错误状态失败")

            if self.audit_repo is not None:
                try:
                    self.audit_repo.record({
                        "action": "run_error",
                        "resource_type": "run",
                        "resource_id": str(self.run_id),
                        "tenant_id": self.tenant_id,
                        "actor_id": self.user_id,
                        "actor_username": self.actor_username,
                        "detail": {
                            "application_id": str(self.application_id),
                            "thread_id": self.thread_id,
                            "error": str(e),
                            "duration_ms": duration_ms,
                        },
                    })
                except Exception:  # noqa: BLE001
                    logger.exception("写 audit_logs 失败")

            await self._notify_webhooks("run_error", {
                "run_id": str(self.run_id),
                "tenant_id": str(self.tenant_id),
                "application_id": str(self.application_id),
                "thread_id": self.thread_id,
                "status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            })

            logger.error("运行失败: run=%s error=%s", self.run_id, e)
            raise

    async def _stream_and_record(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        """用 astream_events 逐节点捕获 start/end，写 run_node_execution + usage ledger。

        返回最后一个 LangGraph 根 chain on_chain_end 的 state dict（无 checkpointer 时读 output 用）。
        """
        node_started_at: dict[str, float] = {}
        final_state: dict[str, Any] | None = None

        async for event in self._compiled.astream_events(
            initial_state, config=self._config(), version="v2"
        ):
            kind = event.get("event")
            name = event.get("name") or event.get("metadata", {}).get("langgraph_node")

            # 根 chain 结束：捕获 final state
            if kind == "on_chain_end" and name == "LangGraph":
                data = event.get("data") or {}
                if isinstance(data.get("output"), dict):
                    final_state = data["output"]
                continue

            if not name or name in ("LangGraph", "start", "end"):
                continue

            if kind == "on_chain_start":
                node_started_at[name] = time.perf_counter()
                if self._on_node_event:
                    node_type = self._node_types.get(name, "")
                    await self._on_node_event("node_start", {
                        "node_id": name, "node_type": node_type,
                    })
            elif kind == "on_chain_end":
                started = node_started_at.pop(name, time.perf_counter())
                duration_ms = int((time.perf_counter() - started) * 1000)
                data = event.get("data") or {}
                output = data.get("output")
                if isinstance(output, dict) and name in output.get("node_outputs", {}):
                    node_out = output["node_outputs"][name]
                    self._record_node_execution(
                        node_id=name,
                        output=node_out,
                        duration_ms=duration_ms,
                        error=None,
                    )
                else:
                    self._record_node_execution(
                        node_id=name,
                        output=output if isinstance(output, dict) else {"raw": str(output)[:8192]},
                        duration_ms=duration_ms,
                        error=None,
                    )
                if self._on_node_event:
                    await self._on_node_event("node_end", {
                        "node_id": name, "status": "success",
                    })
            elif kind == "on_chain_error":
                started = node_started_at.pop(name, time.perf_counter())
                duration_ms = int((time.perf_counter() - started) * 1000)
                err = (event.get("data") or {}).get("error")
                self._record_node_execution(
                    node_id=name,
                    output=None,
                    duration_ms=duration_ms,
                    error=str(err),
                )
                if self._on_node_event:
                    await self._on_node_event("node_end", {
                        "node_id": name, "status": "error",
                    })

        return final_state or {}

    def _record_node_execution(
        self,
        *,
        node_id: str,
        output: dict | None,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        if self.run_repo is None:
            return
        node_type = self._node_types.get(node_id, "unknown")

        token_usage: dict[str, int] | None = None
        if isinstance(output, dict):
            usage = output.get("usage")
            if isinstance(usage, dict):
                token_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "total_tokens": int(usage.get("total_tokens", 0) or 0),
                }

        try:
            self.run_repo.insert_node_execution(
                execute_id=self.run_id,
                node_id=node_id,
                node_type=node_type,
                output=output,
                error_message=error,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                usage=token_usage,
            )
        except Exception:  # noqa: BLE001
            logger.exception("写 run_node_execution 失败: node=%s", node_id)

        if (
            self.usage_repo is not None
            and node_type == "3"  # LLM node
            and error is None
            and token_usage
            and token_usage.get("total_tokens")
        ):
            model_id = ""
            if isinstance(output, dict):
                model_id = output.get("model") or ""
            try:
                self.usage_repo.record_usage(
                    tenant_id=self.tenant_id,
                    application_id=self.application_id,
                    run_id=self.run_id,
                    node_id=node_id,
                    model_id=model_id,
                    prompt_tokens=token_usage["prompt_tokens"],
                    completion_tokens=token_usage["completion_tokens"],
                    total_tokens=token_usage["total_tokens"],
                    user_id=self.user_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("写 tenant_usage_ledger 失败: node=%s", node_id)

    async def _notify_webhooks(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.webhook_repo is None:
            return
        try:
            webhooks = self.webhook_repo.list_for_event(
                self.tenant_id, event_type, self.application_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("查 webhook 列表失败")
            return
        if not webhooks:
            return

        import httpx

        from internal.infrastructure.security.ssrf_guard import validate_outbound_url

        async def _send(wh: dict[str, Any]) -> None:
            url = wh["url"]
            try:
                # 运行时二次校验：挡住 DB 被直接写脏数据 / 历史遗留 URL 绕过创建时校验
                validate_outbound_url(url)
            except Exception:  # noqa: BLE001
                logger.warning("webhook URL 未通过 SSRF 校验，已跳过: url=%s", url)
                return
            try:
                async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                    await client.post(url, json=payload)
            except Exception:  # noqa: BLE001
                logger.warning("webhook 推送失败: url=%s", url)

        for wh in webhooks:
            task = asyncio.create_task(_send(wh))
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
