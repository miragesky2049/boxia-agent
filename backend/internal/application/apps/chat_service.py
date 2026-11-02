"""用户端 chat 应用服务：ReAct 循环 + SSE 事件流 + 会话/消息持久化。

chat 不走 GraphRunner（那是节点级 dag 执行），而是直接调 LLMClient + 工具执行，
把每一轮 LLM/tool 事件包装成前端期望的 SSE 帧。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.apps.ports import RunnerFactory
from internal.application.apps.resource_service import AppResourceService
from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.llm.client import LLMResponse, LLMToolSpec
from internal.domain.repository.apps_protocols import (
    ConversationRepositoryProtocol,
    MessageRepositoryProtocol,
    RunRepositoryProtocol,
)
from internal.domain.repository.protocols import UnitOfWork

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10


def _extract_final_text(output: Any) -> str:
    """从结束节点输出里取最终回答文本；返回变量模式可能没有文本。"""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("output", "content", "answer", "text"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _resume_answer_text(resume: dict[str, Any] | None) -> str:
    """从 resume 载荷里取用户回答文本；人审批准等非回答载荷返回空。"""
    if not isinstance(resume, dict):
        return ""
    value = resume.get("answer", resume.get("content"))
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


@dataclass(frozen=True)
class ChatflowPreparedRun:
    """对话流请求级校验后的运行上下文。

    HTTP 路由在返回 StreamingResponse 之前调用 prepare_chatflow_run，
    会话/线程/参数错误直接以 4xx 返回，不再落进 SSE error 事件。
    """

    application_id: UUID
    message: str
    conversation_id: UUID
    conversation_title: str
    thread_id: str
    resume: dict[str, Any] | None


class ChatService:
    """user 端 chat 服务：组装 LLM + tools + 历史消息，跑 ReAct 循环并产出 SSE 事件。"""

    def __init__(
        self,
        uow: UnitOfWork,
        context: Any,
        principal: Any,
        runner_factory: RunnerFactory,
        *,
        app_service: ApplicationService,
        model_service: ModelService,
        resource_service: AppResourceService,
        conv_repo: ConversationRepositoryProtocol,
        msg_repo: MessageRepositoryProtocol,
        run_repo: RunRepositoryProtocol,
        default_llm_model_id: str,
    ) -> None:
        """runner_factory 与各服务/仓储由组合根注入（web.deps.graph / apps_services），
        应用层不自行构造 infra 具体类，也不反向 import web。"""
        self._uow = uow
        self._context = context
        self._principal = principal
        self._runner_factory = runner_factory
        self._tenant_id = principal.tenant_id
        self._user_id = principal.user_id
        self._app_service = app_service
        self._model_service = model_service
        self._resource_service = resource_service
        self._conv_repo: ConversationRepositoryProtocol = conv_repo
        self._msg_repo: MessageRepositoryProtocol = msg_repo
        self._run_repo: RunRepositoryProtocol = run_repo
        self._default_llm_model_id = default_llm_model_id

    # ========== chat SSE ==========
    async def run_agent_stream(
        self,
        application_id: UUID,
        query: str,
        conversation_id: UUID | None,
        history: list[dict[str, str]] | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """跑一轮 ReAct 对话，产出 (event_name, payload) 序列。路由层负责转 SSE 帧。"""
        # 1. 可见性闸门
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )

        # 2. 会话归属
        if conversation_id is not None:
            conv = self._conv_repo.get_conversation(conversation_id)
            if (
                conv is None
                or conv["user_id"] != self._user_id
                or conv["application_id"] != application_id
                or conv["tenant_id"] != self._tenant_id
            ):
                raise NotFoundError("会话不存在或无权访问")
            cid = conversation_id
        else:
            cid = self._conv_repo.insert_conversation(
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                title=query[:30],
            )

        # 3. 落库 user 消息
        self._msg_repo.append_message(
            conversation_id=cid,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=application_id,
            role="user",
            content=query,
        )

        run_id = uuid4()
        tool_traces: list[dict[str, Any]] = []
        iterations = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        final_content = ""
        last_finish_reason = "stop"
        assistant_tool_calls: list[dict[str, Any]] = []

        try:
            # 4. 读 graph 里的 agent_loop 节点配置
            graph = await self._app_service.get_runtime_graph(application_id, self._tenant_id)
            loop_node = next(
                (n for n in graph.get("nodes", []) if n.get("type") == "agent_loop"),
                None,
            )
            node_cfg = (loop_node or {}).get("config") or {}
            system_prompt = (
                node_cfg.get("system_prompt")
                or f"你是{app_card['name']}。{app_card.get('description') or ''}".strip()
            )
            model_id = node_cfg.get("model_id") or self._default_llm_model_id
            tool_resource_ids = node_cfg.get("tool_resource_ids") or []
            max_rounds = int(node_cfg.get("max_tool_rounds") or MAX_TOOL_ROUNDS)

            # 5. 构造 LLM client
            client = self._model_service.get_client_for_tenant(model_id, self._tenant_id)

            # 6. 构造 tools（LLMToolSpec + 执行表）
            tool_specs, tool_executors = self._build_tools(tool_resource_ids)

            # 7. 组装 messages
            messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            for h in history or []:
                role = h.get("role")
                content = h.get("content") or ""
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": query})

            yield "run_start", {
                "run_id": str(run_id),
                "tools": [t.name for t in tool_specs],
            }

            # 无 tools 时直接走流式：逐 token yield llm_token 事件，前端打字机渲染
            if not tool_specs:
                iterations = 1
                yield "llm_start", {
                    "iteration": iterations,
                    "messages": messages,
                    "tools": [],
                }

                chunks: list[str] = []
                async for chunk in client.chat_stream(messages=messages):
                    delta = chunk.content or ""
                    if delta:
                        chunks.append(delta)
                        yield "llm_token", {
                            "delta": delta,
                        }
                    if chunk.usage.prompt_tokens:
                        usage_total["prompt_tokens"] = chunk.usage.prompt_tokens
                        usage_total["completion_tokens"] = chunk.usage.completion_tokens
                        usage_total["total_tokens"] = chunk.usage.total_tokens
                    if chunk.finish_reason:
                        last_finish_reason = chunk.finish_reason

                final_content = "".join(chunks)
                messages.append({"role": "assistant", "content": final_content})

                yield "llm_end", {
                    "iteration": iterations,
                    "content": final_content,
                    "tool_calls": [],
                    "usage": {
                        "prompt_tokens": usage_total["prompt_tokens"],
                        "completion_tokens": usage_total["completion_tokens"],
                        "total_tokens": usage_total["total_tokens"],
                    },
                }
            else:
                for i in range(max_rounds):
                    iterations = i + 1
                    yield "llm_start", {
                        "iteration": iterations,
                        "messages": messages,
                        "tools": [t.to_openai() for t in tool_specs],
                    }

                    resp: LLMResponse = await client.chat(
                        messages=messages,
                        tools=tool_specs or None,
                    )

                    usage_total["prompt_tokens"] += resp.usage.prompt_tokens
                    usage_total["completion_tokens"] += resp.usage.completion_tokens
                    usage_total["total_tokens"] += resp.usage.total_tokens
                    last_finish_reason = resp.finish_reason

                    tc_out = [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                        for tc in resp.tool_calls
                    ]
                    assistant_tool_calls = tc_out

                    yield "llm_end", {
                        "iteration": iterations,
                        "content": resp.content,
                        "tool_calls": tc_out,
                        "usage": resp.usage.model_dump(),
                    }

                    if not resp.tool_calls:
                        final_content = resp.content
                        messages.append({"role": "assistant", "content": resp.content})
                        break

                    # 有 tool_calls：先把 assistant 消息回灌，再逐个执行 tool
                    messages.append(
                        {
                            "role": "assistant",
                            "content": resp.content,
                            "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
                        }
                    )

                    for tc in resp.tool_calls:
                        raw_args = tc.function.arguments or "{}"
                        try:
                            args_obj: dict[str, Any] = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args_obj = {}

                        yield "tool_start", {
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "arguments": args_obj,
                        }

                        try:
                            observation = await self._execute_tool(
                                tool_executors, tc.function.name, args_obj
                            )
                            is_error = False
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("tool 执行失败 tool=%s", tc.function.name)
                            observation = f"工具执行失败：{exc}"
                            is_error = True

                        tool_traces.append(
                            {
                                "tool_call_id": tc.id,
                                "name": tc.function.name,
                                "observation": observation,
                                "is_error": is_error,
                            }
                        )
                        yield "tool_end", {
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "observation": observation,
                            "is_error": is_error,
                        }
                        messages.append(
                            {"role": "tool", "tool_call_id": tc.id, "content": observation}
                        )
                else:
                    final_content = "已达到最大工具调用轮数，请简化问题后重试。"

            # 8. 落库 assistant 消息(chat 场景不走 run 表,run_id 置空)
            self._msg_repo.append_message(
                conversation_id=cid,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                role="assistant",
                content=final_content,
                tool_calls=assistant_tool_calls or None,
                run_id=None,
                metadata={"usage": usage_total, "iterations": iterations},
            )

            yield "result", {
                "agent_id": str(application_id),
                "run_id": str(run_id),
                "conversation_id": str(cid),
                "content": final_content,
                "tool_traces": tool_traces,
                "iterations": iterations,
                "usage": usage_total,
                "finish_reason": last_finish_reason,
            }
            # 消息落库后统一提交，HTTP 层无需再 commit
            self._uow.commit()
        except Exception as exc:
            logger.exception("chat 运行失败 application=%s", application_id)
            yield "error", {"message": str(exc), "code": "chat_failed"}
        finally:
            yield "final", {}

    # ========== 会话历史读取 ==========
    async def list_conversations(
        self,
        application_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出当前用户在指定应用下的会话列表（按 updated_at 倒序）。"""
        self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        rows = self._conv_repo.list_conversations_by_user(
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=application_id,
            channel="api",
            limit=limit,
            offset=offset,
        )
        return [
            {
                "conversation_id": str(r["id"]),
                "title": r.get("title") or "",
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
            for r in rows
        ]

    async def list_messages(
        self,
        application_id: UUID,
        conversation_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """拉取某个会话的历史消息（升序），用于前端恢复聊天上下文。"""
        self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        conv = self._conv_repo.get_conversation(conversation_id)
        if (
            conv is None
            or conv["user_id"] != self._user_id
            or conv["application_id"] != application_id
            or conv["tenant_id"] != self._tenant_id
        ):
            raise NotFoundError("会话不存在或无权访问")

        rows = self._msg_repo.list_messages_by_conversation(
            conversation_id, limit=limit,
        )
        result: list[dict[str, Any]] = []
        for r in rows:
            if r.get("role") not in ("user", "assistant"):
                continue
            tool_calls = r.get("tool_calls")
            if isinstance(tool_calls, str):
                try:
                    tool_calls = json.loads(tool_calls or "[]")
                except json.JSONDecodeError:
                    tool_calls = []
            result.append({
                "message_id": str(r["id"]),
                "role": r["role"],
                "content": r.get("content") or "",
                "tool_calls": tool_calls or [],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
        return result

    # ========== workflow 非流式运行 ==========
    async def run_workflow(
        self,
        application_id: UUID,
        inputs: dict[str, Any],
        thread_id: str | None,
        conversation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """走 GraphRunner 跑 dag 工作流；人审中断时返回 waiting_approval。"""
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        if app_card.get("flow_type") == "chatflow":
            raise ValidationError("对话流应用请使用对话流运行接口")

        canvas_json = await self._app_service.get_runtime_graph(application_id, self._tenant_id)
        if any(str(node.get("type")) == "18" for node in canvas_json.get("nodes") or []):
            raise ValidationError("工作流中暂不支持问答节点：该节点会中断且没有恢复通道，请改用对话流")

        runner = await self._runner_factory(
            self._app_service,
            self._uow,
            self._context,
            tenant_id=self._tenant_id,
            application_id=application_id,
            thread_id=thread_id,
            current_user_id=self._user_id,
            actor_username=getattr(self._principal, "username", None),
            conversation_id=conversation_id,
        )

        from internal.domain.graph.runtime import GraphInterrupted

        try:
            output = await runner.invoke(inputs)
            self._uow.commit()
            return {
                "status": "success",
                "output": output,
                "thread_id": runner.thread_id,
                "run_id": runner.run_id,
            }
        except GraphInterrupted as exc:
            self._uow.commit()
            return {
                "status": "waiting_approval",
                "thread_id": runner.thread_id,
                "run_id": runner.run_id,
                "approval": exc.interrupt_payload,
            }

    # ========== 对话流流式运行 ==========
    def assert_chatflow_application(self, application_id: UUID) -> dict:
        """HTTP 层先行校验应用类型，避免把 422 包进 SSE 流。"""
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        if app_card.get("flow_type") != "chatflow":
            raise ValidationError("当前应用不是对话流，请使用工作流运行接口")
        return app_card

    def prepare_chatflow_run(
        self,
        application_id: UUID,
        *,
        message: str,
        conversation_id: UUID | None,
        resume: dict[str, Any] | None,
        thread_id: str | None,
    ) -> ChatflowPreparedRun:
        """请求级预检：应用类型、参数组合、会话归属、线程归属。

        必须在返回 StreamingResponse 之前调用，保证鉴权/参数错误以 JSON 4xx 返回，
        而不是在 SSE 流里推一条 error 事件。
        """
        self.assert_chatflow_application(application_id)

        normalized = (message or "").strip()
        if not normalized and resume is None:
            raise ValidationError("message 与 resume 至少提供一个")
        if resume is not None and conversation_id is None:
            raise ValidationError("续跑必须提供 conversation_id")

        if conversation_id is not None:
            conv = self._conv_repo.get_conversation(conversation_id)
            if (
                conv is None
                or conv["user_id"] != self._user_id
                or conv["application_id"] != application_id
                or conv["tenant_id"] != self._tenant_id
            ):
                raise NotFoundError("会话不存在或无权访问")
            cid = conversation_id
            conv_title = str(conv.get("title") or "")
        else:
            conv_title = normalized[:30] or "新对话"
            cid = self._conv_repo.insert_conversation(
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                title=conv_title,
            )

        bound_thread_id = self._bind_chatflow_thread_id(cid, thread_id)
        return ChatflowPreparedRun(
            application_id=application_id,
            message=normalized,
            conversation_id=cid,
            conversation_title=conv_title,
            thread_id=bound_thread_id,
            resume=resume,
        )

    async def run_chatflow_stream(
        self,
        prepared: ChatflowPreparedRun,
        inputs: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """跑一轮对话流并产出 SSE 事件。

        调用前必须已完成 prepare_chatflow_run；本方法只做运行与落库。
        与工作流 run 的区别：
        - 每轮以用户消息驱动，START 注入 USER_INPUT/CONVERSATION_NAME/CONVERSATION_ID
        - 输出节点的 output_message、问答节点的 question 直接作为聊天事件推送
        - 用户消息、中间输出、最终回答落库到 conversation/message
        """
        application_id = prepared.application_id
        message = prepared.message
        cid = prepared.conversation_id
        conv_title = prepared.conversation_title
        resume = prepared.resume

        from internal.domain.graph.runtime import GraphInterrupted

        bound_thread_id = prepared.thread_id
        run_repo = self._run_repo

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def emitter(event_type: str, payload: dict[str, Any]) -> None:
            await queue.put(("event", (event_type, payload)))

        async def make_runner(thread_id: str, run_id: UUID | None = None) -> Any:
            return await self._runner_factory(
                self._app_service,
                self._uow,
                self._context,
                tenant_id=self._tenant_id,
                application_id=application_id,
                thread_id=thread_id,
                run_id=run_id,
                current_user_id=self._user_id,
                actor_username=getattr(self._principal, "username", None),
                conversation_id=cid,
                on_node_event=emitter,
            )

        # 续跑复用上一轮中断的 run_id：既保证审计字段连续，
        # 也避免 message.run_id 外键指向不存在的 run 记录。
        resume_run_id: UUID | None = None
        if resume is not None:
            running = run_repo.get_running_by_thread(
                self._tenant_id, application_id, bound_thread_id,
            )
            if running is not None:
                resume_run_id = running["id"]
        runner = await make_runner(bound_thread_id, run_id=resume_run_id)

        # 上一轮停在提问中断、用户未回答就直接发新消息：放弃旧中断，
        # 换一个子线程重新 invoke，避免整条会话永久卡在 interrupt。
        if resume is None and message:
            history = await runner.list_state_history(limit=1)
            if history and history[0].get("interrupts"):
                bound_thread_id = f"{cid}:{uuid4()}"
                runner = await make_runner(bound_thread_id)

        start_inputs: dict[str, Any] = {
            **(inputs or {}),
            "USER_INPUT": message,
            "CONVERSATION_NAME": conv_title,
            "CONVERSATION_ID": str(cid),
        }

        # 用户消息先落库；先确保 run 记录存在，满足 message.run_id 外键。
        runner.ensure_run(start_inputs if resume is None else {"resume": resume})
        user_text = message or _resume_answer_text(resume)
        if user_text:
            self._msg_repo.append_message(
                conversation_id=cid,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                role="user",
                content=user_text,
                run_id=runner.run_id,
            )

        async def run_task() -> None:
            try:
                if resume is not None:
                    output = await runner.resume(resume)
                else:
                    output = await runner.invoke(start_inputs)
                queue.put_nowait(("output", output))
            except GraphInterrupted as exc:
                queue.put_nowait(("interrupted", exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("对话流运行失败 application=%s", application_id)
                queue.put_nowait(("error", exc))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(run_task())
        yield "run_start", {
            "conversation_id": str(cid),
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
        }

        output: Any = None
        interrupted: GraphInterrupted | None = None
        emitted_outputs: list[str] = []

        try:
            while True:
                kind, payload = await queue.get()
                if kind == "done":
                    break
                if kind == "event":
                    event_type, data = payload
                    if event_type == "output_message":
                        emitted_outputs.append(str((data or {}).get("content") or ""))
                    yield event_type, data
                elif kind == "output":
                    output = payload
                elif kind == "interrupted":
                    interrupted = payload
                elif kind == "error":
                    yield "error", {"message": str(payload), "code": "chatflow_failed"}
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if interrupted is not None:
            await self._handle_chatflow_interrupt(cid, interrupted, runner)
            self._conv_repo.touch(cid)
            payload = interrupted.interrupt_payload or {}
            if payload.get("type") == "question":
                self._uow.commit()
                yield "question", {
                    "node_id": payload.get("node_id"),
                    "question": payload.get("question") or "",
                    "options": payload.get("options") or [],
                    "conversation_id": str(cid),
                    "thread_id": interrupted.thread_id,
                    "run_id": str(runner.run_id),
                }
            else:
                self._uow.commit()
                yield "interrupted", {
                    "approval": payload,
                    "conversation_id": str(cid),
                    "thread_id": interrupted.thread_id,
                    "run_id": str(runner.run_id),
                }
            yield "final", {}
            return

        final_text = _extract_final_text(output)
        if final_text and final_text not in emitted_outputs:
            self._msg_repo.append_message(
                conversation_id=cid,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                application_id=application_id,
                role="assistant",
                content=final_text,
                run_id=runner.run_id,
            )
        self._conv_repo.touch(cid)
        self._uow.commit()

        yield "result", {
            "conversation_id": str(cid),
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
            "content": final_text,
            "output": output,
        }
        yield "final", {}

    def _bind_chatflow_thread_id(
        self,
        conversation_id: UUID,
        thread_id: str | None,
    ) -> str:
        """把客户端 thread_id 绑定到当前会话，阻断跨会话读取 checkpoint。

        允许三种形式：空（默认会话 ID）、纯会话 ID、`<tenant_id>:<business>` 包装前缀；
        business 必须是会话 ID 或以 `<conversation_id>:` 开头的子线程。
        """
        cid = str(conversation_id)
        raw = (thread_id or "").strip()
        if not raw:
            return cid

        tenant_prefix = f"{self._tenant_id}:"
        if raw.startswith(tenant_prefix):
            business = raw[len(tenant_prefix):]
        elif raw == cid or raw.startswith(f"{cid}:"):
            business = raw
        else:
            raise ForbiddenError("thread_id 不属于当前会话")

        if business != cid and not business.startswith(f"{cid}:"):
            raise ForbiddenError("thread_id 不属于当前会话")
        return business

    async def _handle_chatflow_interrupt(
        self,
        conversation_id: UUID,
        interrupted: Any,
        runner: Any,
    ) -> None:
        """中断时把问题落库，保证用户回答后历史仍能还原。"""
        payload = interrupted.interrupt_payload or {}
        if payload.get("type") != "question":
            return
        question = str(payload.get("question") or "").strip()
        if not question:
            return
        self._msg_repo.append_message(
            conversation_id=conversation_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=runner.application_id,
            role="assistant",
            content=question,
            run_id=runner.run_id,
            metadata={
                "type": "question",
                "node_id": payload.get("node_id"),
                "options": payload.get("options") or [],
                "thread_id": interrupted.thread_id,
            },
        )

    # ========== 内部：tools ==========
    def _build_tools(
        self, tool_resource_ids: list[str]
    ) -> tuple[list[LLMToolSpec], dict[str, dict[str, Any]]]:
        """把 resource_id 列表解析为 LLMToolSpec + 执行表。

        第一阶段 tool 执行走 stub（回灌占位文本），真实 HTTP 调用留到下一阶段接 ToolGateway。
        """
        specs: list[LLMToolSpec] = []
        executors: dict[str, dict[str, Any]] = {}
        for raw_id in tool_resource_ids or []:
            try:
                rid = UUID(str(raw_id))
            except (ValueError, TypeError):
                continue
            record = self._resource_service.resolve_for_tenant(rid, self._tenant_id)
            if record is None:
                continue
            cfg = record.get("config") or {}
            name = record.get("name") or cfg.get("tool_name") or f"tool_{rid.hex[:8]}"
            description = record.get("description") or cfg.get("description") or ""
            parameters = cfg.get("parameters") or {
                "type": "object",
                "properties": {},
            }
            specs.append(
                LLMToolSpec(name=name, description=description, parameters=parameters)
            )
            executors[name] = {
                "type": cfg.get("type") or "http",
                "config": cfg,
            }
        return specs, executors

    async def _execute_tool(
        self,
        executors: dict[str, dict[str, Any]],
        name: str,
        args: dict[str, Any],
    ) -> str:
        """执行 tool。第一阶段：stub，返回占位文本。"""
        record = executors.get(name)
        if record is None:
            return f"工具 {name} 未注册。"
        # TODO 下一阶段：接 ToolGateway.invoke_http，按 record['config'] 发 HTTP
        return (
            f"工具 {name} 已调用，参数：{json.dumps(args, ensure_ascii=False)}。"
            f"（第一阶段 stub，真实执行待接入 ToolGateway）"
        )
