"""v4 运行时：编译并执行 graph，记录运行实例 + 节点执行，支持人审 interrupt / resume。"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable
from uuid import UUID

from langgraph.types import Command

from internal.engine.v4.compiler import compile_graph, infer_runtime_mode
from internal.engine.v4.events import NodeExecutionEvent, publish
from internal.engine.v4.nodes.builtin import (
    ModelResolverCtx,
    SubgraphLoaderCtx,
    TenantIdCtx,
    ToolResolverCtx,
)

logger = logging.getLogger(__name__)

# 模型解析器签名：(model_id: str) -> LLMClient
ModelResolver = Callable[[str], Any]

# 子图加载器签名：(application_id: str) -> dict（返回 graph JSON，已按 tenant 应用 effective config）
SubgraphLoader = Callable[[str], dict]

# tool 资源解析器签名：(resource_id: str) -> dict | None
ToolResolver = Callable[[str], Any]


_CHECKPOINTER: Any | None = None


def _get_checkpointer():
    """全局单例 PostgresSaver：持久化 checkpoint，重启不丢。

    懒加载：首次编译 graph 时才建连接（避免模块加载时 context manager 生命周期问题）。
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    from internal.infrastructure.config.settings import get_settings

    settings = get_settings()
    # SQLAlchemy URL 转 psycopg URL：postgresql+psycopg:// -> postgresql://
    db_url = settings.database_url.replace("+psycopg", "")

    from langgraph.checkpoint.postgres import PostgresSaver

    # 用 with 管理连接生命周期，但我们要长期持有 -> 手动 __enter__
    cm = PostgresSaver.from_conn_string(db_url)
    saver = cm.__enter__()
    saver.setup()
    _CHECKPOINTER = saver
    logger.info("PostgresSaver 已初始化，checkpoint 持久化到 %s", db_url.split("@")[-1])
    return saver

# LangGraph 内部事件名过滤：这些不是用户节点，不写 run_node_execution
_INTERNAL_NAMES = {"", "LangGraph", "Graph", "Channel"}


class GraphInterrupted(Exception):
    """图执行被人审 interrupt 暂停。"""
    def __init__(self, interrupt_payload: dict[str, Any]):
        self.interrupt_payload = interrupt_payload
        super().__init__("图执行被人审节点暂停")


class GraphRunner:
    """编译并执行 graph，返回最终输出，支持人审暂停恢复。"""

    def __init__(
        self,
        graph: dict[str, Any],
        tenant_id: UUID | None = None,
        application_id: UUID | None = None,
        model_resolver: ModelResolver | None = None,
        subgraph_loader: SubgraphLoader | None = None,
        tool_resolver: ToolResolver | None = None,
        thread_id: str | None = None,
        run_id: UUID | None = None,
        run_repo: Any | None = None,
        usage_repo: Any | None = None,
        audit_repo: Any | None = None,
        current_user_id: UUID | None = None,
        actor_username: str | None = None,
    ):
        self.graph = graph
        self.tenant_id = tenant_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
        self.application_id = application_id or uuid.uuid4()
        self.runtime_mode = infer_runtime_mode(graph)
        self.thread_id = thread_id or str(uuid.uuid4())
        self.run_id = run_id or uuid.uuid4()
        self._model_resolver = model_resolver
        self._subgraph_loader = subgraph_loader
        self._tool_resolver = tool_resolver
        self._run_repo = run_repo
        self._usage_repo = usage_repo
        self._audit_repo = audit_repo
        # 触发本次运行的最终用户标识：落 audit_logs.actor_id / tenant_usage_ledger.user_id
        self._current_user_id = current_user_id
        self._actor_username = actor_username
        # 节点 id -> type 映射，用于节点执行记录
        self._node_types: dict[str, str] = {
            n.get("id"): n.get("type", "unknown") for n in graph.get("nodes", [])
        }
        # 编译时挂 checkpointer，支持 interrupt 暂停
        self.compiled = compile_graph(graph, checkpointer=_get_checkpointer())

    def _config(self) -> dict[str, Any]:
        # 按 tenant_id 命名空间隔离 thread_id，防止跨租户通过伪造 thread_id 访问他人 checkpoint
        return {"configurable": {"thread_id": f"{self.tenant_id}:{self.thread_id}"}}

    def _extract_interrupt(self) -> dict[str, Any] | None:
        """从 checkpointer 中取出当前等待的人审 interrupt payload。"""
        state = self.compiled.get_state(self._config())
        if not state.next:
            return None
        for task in state.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                return task.interrupts[0].value
        return None

    def _is_user_node(self, name: str) -> bool:
        """判断事件 name 是否对应用户节点（而非 LangGraph 内部链）。"""
        if not name or name.startswith("LangGraph") or name in _INTERNAL_NAMES:
            return False
        return name in self._node_types

    async def _stream_and_record(self, stream_input: dict | Command) -> None:
        """跑 graph 并逐节点落 run_node_execution。"""
        node_started_at: dict[str, float] = {}

        async for event in self.compiled.astream_events(
            stream_input,
            config=self._config(),
            version="v2",
        ):
            kind = event["event"]
            name = event.get("name") or ""
            if not self._is_user_node(name):
                continue

            if kind == "on_chain_start":
                node_started_at[name] = time.perf_counter()
            elif kind == "on_chain_end":
                started = node_started_at.pop(name, time.perf_counter())
                duration_ms = int((time.perf_counter() - started) * 1000)
                data = event.get("data") or {}
                output = data.get("output")
                input_data = data.get("input")
                self._record_node_execution(
                    node_id=name,
                    input_data=input_data if isinstance(input_data, dict) else None,
                    output=output if isinstance(output, dict) else {"value": output},
                    duration_ms=duration_ms,
                )
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

    def _record_node_execution(
        self,
        *,
        node_id: str,
        input_data: dict | None,
        output: dict | None,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """写 run_node_execution；LLM 节点含 usage 时同步写 tenant_usage_ledger。"""
        if self._run_repo is None:
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
            self._run_repo.insert_node_execution(
                run_id=self.run_id,
                node_id=node_id,
                node_type=node_type,
                input_data=input_data,
                output=output,
                error=error,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                token_usage=token_usage,
            )
        except Exception:  # noqa: BLE001
            logger.exception("写 run_node_execution 失败: node=%s", node_id)

        # LLM 节点成功且有 usage -> 落 usage ledger
        if (
            self._usage_repo is not None
            and node_type == "llm"
            and error is None
            and token_usage
            and token_usage.get("total_tokens")
        ):
            model_id = ""
            if isinstance(output, dict):
                model_id = output.get("model") or ""
            try:
                self._usage_repo.record_usage(
                    tenant_id=self.tenant_id,
                    application_id=self.application_id,
                    run_id=self.run_id,
                    node_id=node_id,
                    model_id=model_id,
                    prompt_tokens=token_usage["prompt_tokens"],
                    completion_tokens=token_usage["completion_tokens"],
                    total_tokens=token_usage["total_tokens"],
                    user_id=self._current_user_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("写 tenant_usage_ledger 失败: node=%s", node_id)

    async def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行 graph。如果遇到人审 interrupt，抛 GraphInterrupted。"""
        started_at = time.time()
        logger.info(
            f"开始运行: run={self.run_id} thread={self.thread_id} mode={self.runtime_mode} "
            f"nodes={len(self.graph.get('nodes', []))}"
        )

        if self._run_repo is not None:
            self._run_repo.insert_run(
                run_id=self.run_id,
                tenant_id=self.tenant_id,
                application_id=self.application_id,
                graph_snapshot=self.graph,
                input_data=input_data,
                langgraph_thread_id=self.thread_id,
            )

        publish(NodeExecutionEvent(
            run_id=self.run_id,
            tenant_id=self.tenant_id,
            application_id=self.application_id,
            node_id="__run__",
            node_type="run",
            status="started",
            input=input_data,
        ))

        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None
        tenant_token = TenantIdCtx.set(self.tenant_id)

        try:
            await self._stream_and_record({"input": input_data})
            # 检查是否被 interrupt 暂停
            interrupt_payload = self._extract_interrupt()
            if interrupt_payload is not None:
                logger.info(f"运行被人审暂停: thread={self.thread_id}")
                if self._run_repo is not None:
                    self._run_repo.update_run_status(self.run_id, status="interrupted")
                raise GraphInterrupted(interrupt_payload)

            result = await self.compiled.aget_state(self._config())
            output = result.values.get("output", {}) if result.values else {}
            duration_ms = int((time.time() - started_at) * 1000)

            if self._run_repo is not None:
                self._run_repo.update_run_status(self.run_id, status="success", output=output)

            publish(NodeExecutionEvent(
                run_id=self.run_id,
                tenant_id=self.tenant_id,
                application_id=self.application_id,
                node_id="__run__",
                node_type="run",
                status="success",
                output=output,
                duration_ms=duration_ms,
            ))
            logger.info(f"运行完成: run={self.run_id} duration={duration_ms}ms")
            return output

        except GraphInterrupted:
            raise
        except Exception as e:
            duration_ms = int((time.time() - started_at) * 1000)
            if self._run_repo is not None:
                self._run_repo.update_run_status(
                    self.run_id, status="error", error=str(e)
                )
            if self._audit_repo is not None:
                try:
                    self._audit_repo.record({
                        "action": "run_error",
                        "resource_type": "run",
                        "resource_id": str(self.run_id),
                        "tenant_id": self.tenant_id,
                        "actor_id": self._current_user_id,
                        "actor_username": self._actor_username,
                        "detail": {
                            "application_id": str(self.application_id),
                            "thread_id": self.thread_id,
                            "error": str(e),
                            "duration_ms": duration_ms,
                        },
                    })
                except Exception:  # noqa: BLE001
                    logger.exception("写 audit_logs 失败")
            publish(NodeExecutionEvent(
                run_id=self.run_id,
                tenant_id=self.tenant_id,
                application_id=self.application_id,
                node_id="__run__",
                node_type="run",
                status="error",
                error=str(e),
                duration_ms=duration_ms,
            ))
            logger.error(f"运行失败: run={self.run_id} error={e}")
            raise
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)
            TenantIdCtx.reset(tenant_token)

    async def resume(self, approval: dict[str, Any]) -> dict[str, Any]:
        """人审通过后恢复执行。approval 形如 {"approved": true, "comment": "..."}。"""
        started_at = time.time()
        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None
        tenant_token = TenantIdCtx.set(self.tenant_id)

        try:
            await self._stream_and_record(Command(resume=approval))
            # 检查是否还有下一个 interrupt
            interrupt_payload = self._extract_interrupt()
            if interrupt_payload is not None:
                if self._run_repo is not None:
                    self._run_repo.update_run_status(self.run_id, status="interrupted")
                raise GraphInterrupted(interrupt_payload)

            result = await self.compiled.aget_state(self._config())
            output = result.values.get("output", {}) if result.values else {}
            duration_ms = int((time.time() - started_at) * 1000)
            if self._run_repo is not None:
                self._run_repo.update_run_status(self.run_id, status="success", output=output)
            logger.info(f"恢复运行完成: thread={self.thread_id} duration={duration_ms}ms")
            return output
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)
            TenantIdCtx.reset(tenant_token)

    def get_interrupt_state(self) -> dict[str, Any] | None:
        """查询当前 thread 是否在等人审。"""
        return self._extract_interrupt()
