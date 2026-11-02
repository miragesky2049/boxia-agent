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

from langgraph.types import Command

from internal.domain.canvas.convert import convert_canvas
from internal.domain.canvas.model import CanvasGraph
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import RuntimeEnv, ServiceRegistry
from internal.domain.graph.checkpoint import get_checkpointer

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task] = set()
_UNSET = object()


class GraphInterrupted(Exception):
    """人审中断：节点调 interrupt() 时抛出，携带审批 payload。"""

    def __init__(self, interrupt_payload: dict[str, Any], thread_id: str) -> None:
        super().__init__("workflow waiting for approval")
        self.interrupt_payload = interrupt_payload
        self.thread_id = thread_id


def make_checkpoint_thread_id(tenant_id: UUID, thread_id: str) -> str:
    """把业务 thread_id 包装成 checkpointer key：`<tenant_id>:<thread_id>`。

    A13：跨租户隔离。同一业务 thread_id 在不同租户下落到不同 checkpoint 行，
    避免恶意或误操作跨租户读取对方的中断状态。
    """
    return f"{tenant_id}:{thread_id}"


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
        conversation_id: UUID | None = None,
        variables: dict[str, Any] | None = None,
        user_variable_keys: set[str] | None = None,
        on_user_variables_changed: Any = None,
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
        self.conversation_id = conversation_id
        # A13：业务裸 thread_id（前端传、run 表存、SSE 返回）；checkpoint 用带租户前缀的 key
        raw_thread_id = thread_id or str(uuid.uuid4())
        self.thread_id = self._strip_tenant_prefix(raw_thread_id)
        self.actor_username = actor_username
        # checkpointer 默认 _UNSET 走 get_checkpointer；显式传 None 表示不挂 checkpointer
        self._checkpointer_override = checkpointer
        # 逐节点事件回调：async callable(event_type: str, payload: dict)
        self._on_node_event = on_node_event

        # 应用变量：每次请求以默认值初始化；用户变量键在运行成功后将变化写回持久层
        self.variables: dict[str, Any] = dict(variables or {})
        self._user_variable_keys = set(user_variable_keys or ())
        self._on_user_variables_changed = on_user_variables_changed
        self._initial_user_variables: dict[str, Any] = {
            key: value
            for key, value in self.variables.items()
            if key in self._user_variable_keys
        }

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
            conversation_id=self.conversation_id,
            variables=dict(self.variables),
        )
        self._runtime_env = env

        if self._checkpointer_override is _UNSET:
            checkpointer = await get_checkpointer()
        else:
            checkpointer = self._checkpointer_override
        compiler = Compiler(
            services=self.services,
            event_emitter=self._on_node_event,
        )
        self._compiled = compiler.compile(self._canvas, env, checkpointer=checkpointer)
        self._compiler_instance = compiler

    def _config(self) -> dict[str, Any]:
        # checkpointer=None 时不传 thread_id，否则 langgraph 报 "No checkpointer set"
        if self._checkpointer_override is None:
            return {}
        return {"configurable": {"thread_id": make_checkpoint_thread_id(self.tenant_id, self.thread_id)}}

    def _build_system_vars(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """只读系统变量：工作流仅 USER_ID/RUN_ID；对话流额外注入会话上下文。"""
        data = input_data or {}
        system: dict[str, Any] = {
            "USER_ID": str(self.user_id) if self.user_id else "",
            "RUN_ID": str(self.run_id),
        }
        if self.conversation_id is not None:
            system.update({
                "CONVERSATION_ID": str(self.conversation_id),
                "USER_INPUT": data.get("USER_INPUT", ""),
                "CONVERSATION_NAME": data.get("CONVERSATION_NAME", ""),
            })
        else:
            # 画布试运行 / 工作流也可能直接传 USER_INPUT，保持可见
            if "USER_INPUT" in data:
                system["USER_INPUT"] = data.get("USER_INPUT", "")
            if "CONVERSATION_NAME" in data:
                system["CONVERSATION_NAME"] = data.get("CONVERSATION_NAME", "")
        return system

    def _flush_user_variables(self, final_values: dict[str, Any]) -> None:
        """把本轮对用户变量的写入（落在 state.globals）持久化回存储。"""
        if not self._user_variable_keys or self._on_user_variables_changed is None:
            return
        globals_pool = final_values.get("globals") or {}
        changed = {
            key: globals_pool[key]
            for key in self._user_variable_keys
            if key in globals_pool
            and globals_pool[key] != self._initial_user_variables.get(key)
        }
        if not changed:
            return
        try:
            self._on_user_variables_changed(changed)
        except Exception:  # noqa: BLE001
            logger.exception("用户变量持久化失败 run=%s", self.run_id)

    def _strip_tenant_prefix(self, raw: str) -> str:
        """如果传入的 thread_id 已经带当前租户前缀（例如从 SSE 原样回传），剥掉前缀得到业务裸 ID。

        前缀不是本租户时按业务 ID 原样使用：checkpointer key 仍会加当前租户前缀，
        因此不会读到其它租户的数据；同时兼容 `<conversation_id>:<子线程>` 形式。
        """
        if ":" not in raw:
            return raw
        prefix, _, rest = raw.partition(":")
        try:
            prefix_uuid = uuid.UUID(prefix)
        except (ValueError, TypeError):
            # 不是 UUID 前缀，按业务 thread_id 本身包含冒号处理
            return raw
        if prefix_uuid != self.tenant_id:
            return raw
        return rest or raw

    def ensure_run(self, input_data: dict[str, Any]) -> None:
        """确保 run 记录存在，供 message.run_id 外键与审计字段引用。

        用户消息会在 invoke 之前落库，因此需要先建 run；resume 复用已中断的 run 时
        这里直接命中已有记录，不会重复插入。
        """
        if self.run_repo is None:
            return
        try:
            get_run = getattr(self.run_repo, "get_run", None)
            if get_run is not None and get_run(self.run_id) is not None:
                return
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

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行工作流，返回最终 output。人审中断本次不触发。"""
        started_at = time.time()
        await self._ensure_compiled()
        self.ensure_run(input_data)

        # A8：从编译器取 graph 级变量池默认值，合并到初始 globals
        default_globals: dict[str, Any] = {}
        if getattr(self, "_compiler_instance", None) is not None:
            try:
                default_globals = self._compiler_instance.default_globals()
            except Exception:  # noqa: BLE001
                logger.exception("计算 graph 级变量默认值失败，按空池继续")

        initial_state = {
            "input": input_data,
            "node_outputs": {},
            # 应用变量作为初始 globals 的一部分，运行期节点写入会覆盖默认值
            "globals": {**default_globals, **self.variables},
            "variables": dict(self.variables),
            "system": self._build_system_vars(input_data),
            "env": {
                "tenant_id": str(self.tenant_id),
                "user_id": str(self.user_id) if self.user_id else None,
                "run_id": str(self.run_id),
                "thread_id": self.thread_id,
                "conversation_id": (
                    str(self.conversation_id) if self.conversation_id else None
                ),
            },
            "output": {},
            "errors": {},
        }

        try:
            final_state_values = await self._stream_and_record(initial_state)

            # 中断检测：有 checkpointer 时从持久化 state 检查是否有人审 interrupt
            interrupt_payload = None
            final_values: dict[str, Any] = {}
            if self._checkpointer_override is not None:
                snapshot = await self._compiled.aget_state(self._config())
                if snapshot.tasks:
                    for task in snapshot.tasks:
                        if getattr(task, "interrupts", None):
                            interrupt_payload = task.interrupts[0].value
                            break
                final_values = dict(snapshot.values or {})
                output = final_values.get("output", {})
            else:
                final_values = dict(final_state_values or {})
                output = final_values.get("output", {})

            # 用户变量：运行成功后把本轮变化写回持久层
            if interrupt_payload is None:
                self._flush_user_variables(final_values)

            duration_ms = int((time.time() - started_at) * 1000)

            # 人审中断：标记 run 为 interrupted，抛 GraphInterrupted
            if interrupt_payload is not None:
                if self.run_repo is not None:
                    try:
                        self.run_repo.update_run_status(
                            self.run_id, execute_status="interrupted",
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("更新 run 状态为 interrupted 失败")
                raise GraphInterrupted(interrupt_payload, self.thread_id)

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

    async def invoke_node(self, node_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """单节点试运行：只执行指定节点，不写 run 记录、不改变全图运行语义。

        Args:
            node_id: 画布内的目标节点 ID。
            input_data: 试运行表单入参，覆盖节点在画布中配置的入参值。

        Returns:
            {"node_id", "node_type", "status", "outputs", "error", "duration_ms"}；
            handler 抛错时 status=error、error 为异常信息，不移交给调用方异常栈。
        """
        started_at = time.time()
        await self._ensure_compiled()

        assert self._canvas is not None
        try:
            canvas_node = self._canvas.node_by_id(node_id)
        except KeyError as exc:
            raise ValueError(f"画布不存在节点: {node_id}") from exc

        default_globals: dict[str, Any] = {}
        try:
            default_globals = self._compiler_instance.default_globals()
        except Exception:  # noqa: BLE001
            logger.exception("单节点试运行计算变量池默认值失败，按空池继续")

        status = "success"
        error_message: str | None = None
        outputs: dict[str, Any] = {}
        try:
            result = await self._compiler_instance.execute_node_only(
                canvas_node,
                self._runtime_env,
                input_data,
                default_globals,
                variables_pool=self.variables,
                system_vars=self._build_system_vars(input_data),
            )
            outputs = result["outputs"]
            error_message = result["error"] or None
            if error_message:
                status = "error"
        except Exception as exc:  # noqa: BLE001
            logger.warning("单节点试运行失败: node=%s error=%s", node_id, exc)
            status = "error"
            error_message = str(exc)

        return {
            "node_id": canvas_node.id,
            "node_type": canvas_node.type.value,
            "status": status,
            "outputs": outputs,
            "error": error_message,
            "duration_ms": int((time.time() - started_at) * 1000),
        }

    async def resume(self, resume_payload: dict[str, Any]) -> dict[str, Any]:
        """人审批准后续跑工作流。

        前提：invoke 已经抛出 GraphInterrupted，state 已持久化在 checkpointer。
        用同一个 thread_id + Command(resume=resume_payload) 继续执行。

        Args:
            resume_payload: 审批结果，如 {"approved": True, "approver": "zhangsan", "comment": "ok"}

        Returns:
            最终 output（和正常 invoke 成功返回一致）

        Raises:
            GraphInterrupted: 再次遇到新的人审节点中断
        """
        started_at = time.time()
        await self._ensure_compiled()
        self.ensure_run({"resume": resume_payload})

        if self._checkpointer_override is None:
            raise RuntimeError("resume 需要 checkpointer 开启（人审状态持久化）")

        # 用 Command(resume=...) 让 langgraph 从 interrupt 点继续
        command = Command(resume=resume_payload)

        try:
            await self._stream_and_record(command)

            snapshot = await self._compiled.aget_state(self._config())
            final_values = dict(snapshot.values or {})
            output = final_values.get("output", {})

            # 检查是否还有下一个人审中断
            if snapshot.tasks:
                for task in snapshot.tasks:
                    if getattr(task, "interrupts", None):
                        interrupt_payload = task.interrupts[0].value
                        if self.run_repo is not None:
                            try:
                                self.run_repo.update_run_status(
                                    self.run_id, execute_status="interrupted",
                                )
                            except Exception:  # noqa: BLE001
                                logger.exception("更新 run 状态为 interrupted 失败")
                        raise GraphInterrupted(interrupt_payload, self.thread_id)

            # 用户变量：续跑成功后把本轮变化写回持久层
            self._flush_user_variables(final_values)

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
            raise

    async def list_state_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """A13：列出当前 thread 的 checkpoint 历史（按时间倒序），用于历史重放 / 审计。

        返回每个 checkpoint 的：checkpoint_id / next 节点 / 是否有待处理 interrupt /
        output 摘要。无 checkpointer 时返回空列表。
        """
        if self._checkpointer_override is None:
            return []
        await self._ensure_compiled()
        result: list[dict[str, Any]] = []
        # langgraph get_state_history 返回同步 generator（非 async）
        for snapshot in self._compiled.get_state_history(self._config(), limit=limit):
            interrupts: list[dict[str, Any]] = []
            for task in getattr(snapshot, "tasks", []) or []:
                for it in getattr(task, "interrupts", []) or []:
                    interrupts.append({"value": getattr(it, "value", None)})
            values = getattr(snapshot, "values", {}) or {}
            result.append({
                "checkpoint_id": str(getattr(snapshot.config, "configurable", {}).get("checkpoint_id", "")),
                "next": list(getattr(snapshot, "next", []) or []),
                "interrupts": interrupts,
                "output": values.get("output", {}),
                "node_outputs_keys": list((values.get("node_outputs") or {}).keys()),
            })
        return result

    async def _stream_and_record(self, initial_state: dict[str, Any] | Command) -> dict[str, Any]:
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
                    data = event.get("data") or {}
                    await self._on_node_event("node_start", {
                        "node_id": name, "node_type": node_type,
                        "inputs": data.get("input"),
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
                    node_out = output if isinstance(output, dict) else {"raw": str(output)[:8192]}
                    self._record_node_execution(
                        node_id=name,
                        output=node_out,
                        duration_ms=duration_ms,
                        error=None,
                    )
                if self._on_node_event:
                    await self._on_node_event("node_end", {
                        "node_id": name, "status": "success",
                        "outputs": node_out, "duration_ms": duration_ms,
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
                        "error": str(err), "duration_ms": duration_ms,
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
