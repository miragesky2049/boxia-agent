"""runtime：编译并执行 graph，记录运行实例 + 节点执行，支持人审 interrupt / resume。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable
from uuid import UUID

from langgraph.types import Command

from internal.engine.graph.compiler import compile_graph, infer_runtime_mode
from internal.engine.graph.events import NodeExecutionEvent, publish
from internal.engine.graph.nodes.builtin import (
    KnowledgeResolverCtx,
    ModelResolverCtx,
    RetrievalServiceCtx,
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
_CHECKPOINTER_LOCK: Any | None = None


async def _get_checkpointer():
    """全局单例 AsyncPostgresSaver：持久化 checkpoint，重启不丢。

    异步懒加载：首次 invoke/resume 时才建连接。
    必须用 AsyncPostgresSaver（同步 PostgresSaver 的 aget_tuple 直接 raise NotImplementedError，
    而 astream_events / aget_state 走异步路径）。
    """
    global _CHECKPOINTER, _CHECKPOINTER_LOCK
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    import asyncio

    if _CHECKPOINTER_LOCK is None:
        _CHECKPOINTER_LOCK = asyncio.Lock()

    async with _CHECKPOINTER_LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER

        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        # SQLAlchemy URL 转 psycopg URL：postgresql+psycopg:// -> postgresql://
        db_url = settings.database_url.replace("+psycopg", "")

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        cm = AsyncPostgresSaver.from_conn_string(db_url)
        saver = await cm.__aenter__()
        await saver.setup()
        # 持有 context manager 防止 __aexit__ 关闭连接
        saver._cm = cm  # type: ignore[attr-defined]
        _CHECKPOINTER = saver
        logger.info("AsyncPostgresSaver 已初始化，checkpoint 持久化到 %s", db_url.split("@")[-1])
        return saver

# LangGraph 内部事件名过滤：这些不是用户节点，不写 run_node_execution
_INTERNAL_NAMES = {"", "LangGraph", "Graph", "Channel"}

# 后台 webhook 推送任务集合：保持引用防止 event loop 在任务完成前 GC
_BACKGROUND_TASKS: set[asyncio.Task] = set()


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
        retrieval_service: Any | None = None,
        knowledge_resolver: Any | None = None,
        webhook_repo: Any | None = None,
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
        self._retrieval_service = retrieval_service
        self._knowledge_resolver = knowledge_resolver
        self._webhook_repo = webhook_repo
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
        # 编译延迟到 async _ensure_compiled()：checkpointer 是异步资源，不能在 __init__ 里建
        self.compiled: Any = None

    async def _ensure_compiled(self) -> None:
        """首次 invoke/resume 时异步编译 graph（挂 AsyncPostgresSaver）。"""
        if self.compiled is None:
            checkpointer = await _get_checkpointer()
            self.compiled = compile_graph(self.graph, checkpointer=checkpointer)

    def _config(self) -> dict[str, Any]:
        # 按 tenant_id 命名空间隔离 thread_id，防止跨租户通过伪造 thread_id 访问他人 checkpoint
        return {"configurable": {"thread_id": f"{self.tenant_id}:{self.thread_id}"}}

    def _config_for_thread(self, thread_id: str) -> dict[str, Any]:
        """为指定 thread_id 构造 config（time-travel 分叉时用新 thread_id）。"""
        return {"configurable": {"thread_id": f"{self.tenant_id}:{thread_id}"}}

    async def _extract_interrupt(self) -> dict[str, Any] | None:
        """从 checkpointer 中取出当前等待的人审 interrupt payload。"""
        state = await self.compiled.aget_state(self._config())
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
        await self._ensure_compiled()
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
        retrieval_token = (
            RetrievalServiceCtx.set(self._retrieval_service) if self._retrieval_service else None
        )
        knowledge_token = (
            KnowledgeResolverCtx.set(self._knowledge_resolver) if self._knowledge_resolver else None
        )

        try:
            await self._stream_and_record({"input": input_data})
            # 检查是否被 interrupt 暂停
            interrupt_payload = await self._extract_interrupt()
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
            await self._notify_webhooks("run_finished", {
                "run_id": str(self.run_id),
                "tenant_id": str(self.tenant_id),
                "application_id": str(self.application_id),
                "thread_id": self.thread_id,
                "status": "success",
                "output": output,
                "duration_ms": duration_ms,
            })
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
            await self._notify_webhooks("run_error", {
                "run_id": str(self.run_id),
                "tenant_id": str(self.tenant_id),
                "application_id": str(self.application_id),
                "thread_id": self.thread_id,
                "status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            })
            logger.error(f"运行失败: run={self.run_id} error={e}")
            raise
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)
            if retrieval_token is not None:
                RetrievalServiceCtx.reset(retrieval_token)
            if knowledge_token is not None:
                KnowledgeResolverCtx.reset(knowledge_token)
            TenantIdCtx.reset(tenant_token)

    async def resume(self, approval: dict[str, Any]) -> dict[str, Any]:
        """人审通过后恢复执行。approval 形如 {"approved": true, "comment": "..."}。"""
        started_at = time.time()
        await self._ensure_compiled()
        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None
        tenant_token = TenantIdCtx.set(self.tenant_id)
        retrieval_token = (
            RetrievalServiceCtx.set(self._retrieval_service) if self._retrieval_service else None
        )
        knowledge_token = (
            KnowledgeResolverCtx.set(self._knowledge_resolver) if self._knowledge_resolver else None
        )

        try:
            await self._stream_and_record(Command(resume=approval))
            # 检查是否还有下一个 interrupt
            interrupt_payload = await self._extract_interrupt()
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
            if retrieval_token is not None:
                RetrievalServiceCtx.reset(retrieval_token)
            if knowledge_token is not None:
                KnowledgeResolverCtx.reset(knowledge_token)
            TenantIdCtx.reset(tenant_token)

    async def get_interrupt_state(self) -> dict[str, Any] | None:
        """查询当前 thread 是否在等人审。"""
        await self._ensure_compiled()
        return await self._extract_interrupt()

    async def _notify_webhooks(self, event_type: str, payload: dict[str, Any]) -> None:
        """异步推送 webhook 通知；失败不阻塞主流程。"""
        if self._webhook_repo is None:
            return
        try:
            webhooks = self._webhook_repo.list_for_event(
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
            try:
                # 发送前二次校验 DNS（防御创建后域名切换到内网）
                validate_outbound_url(wh["url"])
                # follow_redirects=False：防止 302 跳到内网地址绕过 SSRF 校验
                async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                    await client.post(wh["url"], json=payload)
            except Exception:  # noqa: BLE001
                logger.warning("webhook 推送失败: url=%s", wh["url"])

        # fire-and-forget：保持 task 引用防止 GC，主流程不阻塞
        for wh in webhooks:
            task = asyncio.create_task(_send(wh))
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def list_checkpoint_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出当前 thread 的 checkpoint 历史（time-travel 用）。

        每条包含：checkpoint_id / 待执行节点 / state 摘要 / 创建时间。
        """
        await self._ensure_compiled()
        result: list[dict[str, Any]] = []
        async for state in self.compiled.aget_state_history(self._config(), limit=limit):
            values = state.values or {}
            result.append({
                "checkpoint_id": state.config["configurable"].get("checkpoint_id"),
                "next_nodes": list(state.next or []),
                "input": values.get("input"),
                "output": values.get("output"),
                "node_count": len([k for k in values.keys() if k not in ("input", "output")]),
                "created_at": getattr(state.metadata, "created_at", None),
            })
        return result

    async def fork_from_checkpoint(
        self,
        source_thread_id: str,
        checkpoint_id: str,
        new_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """从历史 checkpoint 分叉：复制 state 到新 thread，然后从该状态继续跑。

        Args:
            source_thread_id: 原 run 的 thread_id
            checkpoint_id: 要分叉的 checkpoint id（来自 list_checkpoint_history）
            new_input: 可选，覆盖 input 字段（不改则沿用分叉点的 input）

        Returns:
            {"new_thread_id": str, "output": dict}
        """
        await self._ensure_compiled()
        source_config = self._config_for_thread(source_thread_id)
        source_config["configurable"]["checkpoint_id"] = checkpoint_id

        # 取源 checkpoint 的 state
        source_state = await self.compiled.aget_state(source_config)
        values = dict(source_state.values or {})
        if new_input is not None:
            values["input"] = new_input

        # 新 thread_id
        new_thread_id = str(uuid.uuid4())
        new_config = self._config_for_thread(new_thread_id)

        # 用 update_state 把源 state 写到新 thread（这会创建一个新 checkpoint）
        await self.compiled.aupdate_state(
            new_config,
            values=values,
        )

        # 从新 thread 继续跑（无 input，因为 state 已就绪）
        self.thread_id = new_thread_id
        started_at = time.time()

        model_token = ModelResolverCtx.set(self._model_resolver) if self._model_resolver else None
        subgraph_token = (
            SubgraphLoaderCtx.set(self._subgraph_loader) if self._subgraph_loader else None
        )
        tool_token = ToolResolverCtx.set(self._tool_resolver) if self._tool_resolver else None
        tenant_token = TenantIdCtx.set(self.tenant_id)
        retrieval_token = (
            RetrievalServiceCtx.set(self._retrieval_service) if self._retrieval_service else None
        )
        knowledge_token = (
            KnowledgeResolverCtx.set(self._knowledge_resolver) if self._knowledge_resolver else None
        )

        try:
            await self._stream_and_record(None)
            interrupt_payload = await self._extract_interrupt()
            if interrupt_payload is not None:
                if self._run_repo is not None:
                    self._run_repo.update_run_status(self.run_id, status="interrupted")
                raise GraphInterrupted(interrupt_payload)

            result = await self.compiled.aget_state(self._config())
            output = result.values.get("output", {}) if result.values else {}
            duration_ms = int((time.time() - started_at) * 1000)
            if self._run_repo is not None:
                self._run_repo.update_run_status(self.run_id, status="success", output=output)
            logger.info(
                f"分叉运行完成: source_thread={source_thread_id} new_thread={new_thread_id} "
                f"duration={duration_ms}ms"
            )
            return {"new_thread_id": new_thread_id, "output": output}
        finally:
            if model_token is not None:
                ModelResolverCtx.reset(model_token)
            if subgraph_token is not None:
                SubgraphLoaderCtx.reset(subgraph_token)
            if tool_token is not None:
                ToolResolverCtx.reset(tool_token)
            if retrieval_token is not None:
                RetrievalServiceCtx.reset(retrieval_token)
            if knowledge_token is not None:
                KnowledgeResolverCtx.reset(knowledge_token)
            TenantIdCtx.reset(tenant_token)
