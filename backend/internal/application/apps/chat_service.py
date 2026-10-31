"""用户端 chat 应用服务：ReAct 循环 + SSE 事件流 + 会话/消息持久化。

chat 不走 GraphRunner（那是节点级 dag 执行），而是直接调 LLMClient + 工具执行，
把每一轮 LLM/tool 事件包装成前端期望的 SSE 帧。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.model_service import ModelService
from internal.application.apps.resource_service import AppResourceService
from internal.application.errors import NotFoundError, ValidationError
from internal.domain.repository.protocols import UnitOfWork
from internal.engine.llm import LLMToolSpec, LLMResponse
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import MessageRepository

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10


class ChatService:
    """user 端 chat 服务：组装 LLM + tools + 历史消息，跑 ReAct 循环并产出 SSE 事件。"""

    def __init__(
        self,
        uow: UnitOfWork,
        context: Any,
        principal: Any,
    ) -> None:
        self._uow = uow
        self._context = context
        self._principal = principal
        self._tenant_id = principal.tenant_id
        self._user_id = principal.user_id
        self._app_service = ApplicationService(uow)
        self._model_service = ModelService(uow.session)
        self._resource_service = AppResourceService(uow.session)
        self._conv_repo = ConversationRepository(uow.session)
        self._msg_repo = MessageRepository(uow.session)

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
            settings = get_settings()
            model_id = node_cfg.get("model_id") or settings.llm_model_id
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
    ) -> dict[str, Any]:
        """走 GraphRunner 跑 dag 工作流；人审中断时返回 waiting_approval。"""
        from web.deps.graph import build_runner  # 延迟 import 避免反向依赖

        self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )

        runner = await build_runner(
            self._app_service,
            self._uow,
            self._context,
            tenant_id=self._tenant_id,
            application_id=application_id,
            thread_id=thread_id,
            current_user_id=self._user_id,
            actor_username=getattr(self._principal, "username", None),
        )

        from internal.engine.runtime import GraphInterrupted

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
