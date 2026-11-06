"""Agent 循环节点（coze agent_loop，本项目 type_code=100）。

独立图协议：plan / execute / reflect 三阶段，非 Dag 节点。

config 约定：
- modleName: 主模型 ID（同 LLM 节点）
- systemPrompt: 系统提示词（agent 角色）
- tools: 向 LLM 暴露的工具 schema（OpenAI tools 数组）；同时构成执行白名单，
  模型调用未声明工具时拒绝执行（见 react.run_react_loop）
- maxToolRounds: execute 阶段 ReAct 最大轮次（默认 5）
- maxReflectRounds: reflect 最大迭代轮次（默认 3，防止 plan→reflect 死循环）
- plannerPrompt: 可选，plan 阶段系统提示词（默认内置）
- reflectorPrompt: 可选，reflect 阶段系统提示词（默认内置）

运行期入参（ctx.eval_context.input，20261106 P3 chat 兼容通道专用；
画布试运行/工作流不携带这些键，行为与改造前一致）：
- react_only: 跳过 plan/reflect，只跑一轮 execute（对齐旧 chat SSE 通道的调用成本与语义）
- history: 多轮消息 [{role, content}, ...]，拼在 system 与当前问题之间
- context: AgentRunContext 的 to_storage_dict 平铺形态（画布入参需 JSONB 可
  序列化，20261106 review 修正），节点内还原后透传给 LLM 请求（租户 header
  与 chat 旧通道一致）；已是 AgentRunContext 实例时原样使用
- max_tool_rounds: 覆盖 config.maxToolRounds（chat 通道沿用旧默认 10）

协议流程：
1. PLAN：LLM 把用户 query 拆解成结构化任务列表 JSON：
   {"tasks": [{"id": "...", "goal": "...", "acceptance": "..."}, ...]}
2. EXECUTE：对整批 tasks 跑一次 ReAct 循环（用户 query + 已知任务清单作 system），
   工具执行结果 + LLM 最终 answer 作为 execute 输出。
3. REFLECT：LLM 根据 execute 产出判定是否达标：
   {"done": true/false, "critique": "...", "missing": "..."}
   若 done=false 且未达 maxReflectRounds：把 critique 追加进 messages 回到 execute。
   若 done=true 或轮次耗尽：返回最终 answer。

依赖：
- ctx.services.get("llm")：LLMClient（async chat(messages, tools, ...) -> LLMResponse）
- ctx.services.get("tool_executor")：可选，async (name, args) -> str
"""

from __future__ import annotations

import json
import logging
from typing import Any

from internal.domain.agent.react import (
    accumulate_usage,
    build_tool_specs,
    run_react_loop,
)
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler
from internal.domain.llm.client import LLMToolSpec

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_ROUNDS = 5
DEFAULT_MAX_REFLECT_ROUNDS = 3

DEFAULT_PLANNER_PROMPT = (
    "你是任务规划器。把用户目标拆解为 1~5 个可执行的子任务。"
    "输出 JSON：{\"tasks\": [{\"id\": \"t1\", \"goal\": \"...\", \"acceptance\": \"...\"}]}。"
    "不要输出 JSON 以外的任何字符。"
)

DEFAULT_REFLECTOR_PROMPT = (
    "你是质量评审。根据原始目标和执行结果判断是否已经完成："
    "输出 JSON：{\"done\": true/false, \"critique\": \"简短问题描述\", \"suggestion\": \"下一步建议\"}。"
    "不要输出 JSON 以外的任何字符。"
)


class AgentLoopNodeHandler(NodeHandler):
    """plan/execute/reflect 三阶段 Agent 循环节点。"""

    type_name = NodeType.AGENT_LOOP.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config or {}
        # 20261106 P3 服务端兼容契约：chat 入口以 graph 入参额外携带
        # react_only（跳过 plan/reflect，仅跑 ReAct）与 history（多轮消息）。
        # 画布试运行/工作流不传这两个键，行为与改造前完全一致。
        runtime_input: dict[str, Any] = {}
        if ctx.eval_context is not None and isinstance(ctx.eval_context.input, dict):
            runtime_input = ctx.eval_context.input
        react_only = bool(runtime_input.get("react_only"))
        history_raw = runtime_input.get("history")
        history = [h for h in history_raw if isinstance(h, dict)] if isinstance(history_raw, list) else []
        chat_context = _resolve_run_context(runtime_input.get("context"))
        user_input = str(
            ctx.inputs.get("input") or runtime_input.get("input") or runtime_input.get("USER_INPUT") or ""
        )

        model_id = _to_str(config.get("modleName") or config.get("modelName"))
        system_prompt = _to_str(config.get("systemPrompt"))
        planner_prompt = _to_str(config.get("plannerPrompt")) or DEFAULT_PLANNER_PROMPT
        reflector_prompt = _to_str(config.get("reflectorPrompt")) or DEFAULT_REFLECTOR_PROMPT
        max_tool_rounds = (
            _to_int(runtime_input.get("max_tool_rounds"))
            or _to_int(config.get("maxToolRounds"))
            or DEFAULT_MAX_TOOL_ROUNDS
        )
        max_reflect_rounds = _to_int(config.get("maxReflectRounds")) or DEFAULT_MAX_REFLECT_ROUNDS

        tool_specs = build_tool_specs(config.get("tools"))
        tool_executor = (
            ctx.services.get("tool_executor") if ctx.services.has("tool_executor") else None
        )

        if not ctx.services.has("llm"):
            return NodeResult(outputs={
                "output": f"[AgentLoop stub] model={model_id} input={user_input[:80]}",
                "plan": [],
                "iterations": 0,
            })

        llm = ctx.services.get("llm")
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        async def _emit(etype: str, payload: dict[str, Any]) -> None:
            if ctx.emit_event is None:
                return
            try:
                await ctx.emit_event(etype, {"node_id": ctx.node_id, **payload})
            except Exception:  # noqa: BLE001
                logger.exception("emit agent_loop trace event failed: %s", etype)

        # 1. PLAN（react_only：chat 兼容契约不需要计划事件，也不该多付一次 LLM 调用）
        plan_tasks = (
            []
            if react_only
            else await self._plan(ctx, _emit, llm, planner_prompt, user_input, usage_total, model_id)
        )

        # 2. EXECUTE / REFLECT 迭代
        execution_messages = self._build_execution_messages(
            system_prompt=system_prompt,
            user_input=user_input,
            plan_tasks=plan_tasks,
            history=history,
        )
        final_answer = ""
        reflect_history: list[dict[str, Any]] = []

        # LLM 扩展参数：画布经 LLMServiceAdapter 必须按 model 解析 client；
        # context 为 chat 兼容通道透传的 AgentRunContext（租户 header）。
        execute_chat_kwargs: dict[str, Any] = {}
        if model_id:
            execute_chat_kwargs["model"] = model_id
        if chat_context is not None:
            execute_chat_kwargs["context"] = chat_context

        async def _do_execute(reflect_round: int) -> str:
            execute_output = await self._execute(
                ctx=ctx,
                emit=_emit,
                llm=llm,
                tool_specs=tool_specs,
                tool_executor=tool_executor,
                messages=execution_messages,
                model_id=model_id,
                max_tool_rounds=max_tool_rounds,
                usage_total=usage_total,
                reflect_round=reflect_round,
                chat_kwargs=execute_chat_kwargs,
            )
            return execute_output["content"]

        if react_only:
            final_answer = await _do_execute(0)
        else:
            for reflect_round in range(max_reflect_rounds):
                final_answer = await _do_execute(reflect_round)

                judgment = await self._reflect(
                    ctx=ctx,
                    emit=_emit,
                    llm=llm,
                    reflector_prompt=reflector_prompt,
                    user_input=user_input,
                    plan_tasks=plan_tasks,
                    execute_output=final_answer,
                    usage_total=usage_total,
                    reflect_round=reflect_round,
                    model_id=model_id,
                )
                reflect_history.append(judgment)

                if judgment.get("done"):
                    break

                suggestion = str(judgment.get("suggestion") or judgment.get("critique") or "")
                if not suggestion:
                    break
                execution_messages.append({
                    "role": "user",
                    "content": f"上一轮结果未达标：{suggestion}。请基于上述反馈继续推进，避免重复已完成的步骤。",
                })

        return NodeResult(
            outputs={
                "output": final_answer,
                "plan": plan_tasks,
                "reflect_history": reflect_history,
                "model": model_id,
            },
            usage=usage_total,
        )

    # ---------- PLAN ----------
    async def _plan(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        planner_prompt: str,
        user_input: str,
        usage_total: dict[str, int],
        model_id: str = "",
    ) -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_input},
        ]
        await emit("prompt_text", {
            "phase": "plan",
            "messages": _messages_for_trace(messages),
        })
        chat_kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
        if model_id:
            chat_kwargs["model"] = model_id
        try:
            resp = await llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan 阶段 LLM 调用失败: %s", exc)
            return [{"id": "t1", "goal": user_input, "acceptance": "直接回答用户问题"}]

        accumulate_usage(usage_total, resp.usage)
        plan_text = getattr(resp, "content", "") or ""
        await emit("prompt_text", {
            "phase": "plan",
            "role": "assistant",
            "content": plan_text,
        })
        parsed = _safe_json(plan_text)
        tasks = parsed.get("tasks") if isinstance(parsed, dict) else None
        if not isinstance(tasks, list) or not tasks:
            return [{"id": "t1", "goal": user_input, "acceptance": "直接回答用户问题"}]
        return [t for t in tasks if isinstance(t, dict)]

    # ---------- EXECUTE（ReAct 循环，走共享内核 react.run_react_loop）----------
    async def _execute(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        tool_specs: list[LLMToolSpec],
        tool_executor: Any,
        messages: list[dict[str, Any]],
        model_id: str,
        max_tool_rounds: int,
        usage_total: dict[str, int],
        reflect_round: int,
        chat_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 20260731 双轨合并：内层 ReAct 循环收敛到 react.run_react_loop，
        # 本方法只负责把内核事件映射为画布 trace 事件（既有协议名与字段保持不变）。
        # 20261106 P3 服务端兼容契约：additive 补齐 chat SSE 映射所需字段
        # （iteration/tools/usage/finish_reason/id/tool_call_id/arguments_parsed/is_error），
        # 画布旧消费方读取的原有键语义不变。
        # 异常范围与迁移前一致：只兜 LLM 调用（内核 __anext__）异常；
        # 事件映射错误属于代码缺陷，照常上抛，不得伪装成模型回复。
        final_content = ""
        event_iter = run_react_loop(
            llm=llm,
            messages=messages,
            tool_specs=tool_specs,
            tool_executor=tool_executor,
            max_rounds=max_tool_rounds,
            chat_kwargs=chat_kwargs or {},
            max_rounds_message="（execute 达到最大工具轮次）",
        ).__aiter__()
        while True:
            try:
                event = await event_iter.__anext__()
            except StopAsyncIteration:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("execute 阶段 LLM 调用失败: %s", exc)
                final_content = f"[execute error] {exc}"
                break

            payload = event.payload
            if event.kind == "llm_start":
                await emit("prompt_text", {
                    "phase": "execute",
                    "reflect_round": reflect_round,
                    "tool_round": payload["iteration"] - 1,
                    "iteration": payload["iteration"],
                    "tools": payload["tools"],
                    "messages": _messages_for_trace(payload["messages"]),
                })
            elif event.kind == "llm_end":
                # 逐轮累计 usage：即使后续轮次 LLM 异常，已消耗 token 不丢
                accumulate_usage(usage_total, payload["usage"])
                await emit("prompt_text", {
                    "phase": "execute",
                    "reflect_round": reflect_round,
                    "tool_round": payload["iteration"] - 1,
                    "iteration": payload["iteration"],
                    "role": "assistant",
                    "content": payload["content"],
                    "usage": payload["usage"],
                    "finish_reason": payload["finish_reason"],
                    "tool_calls": [
                        {"id": tc["id"], "name": tc["name"], "arguments": tc["arguments"]}
                        for tc in payload["tool_calls"]
                    ],
                })
            elif event.kind == "tool_start":
                await emit("tool_call_start", {
                    "name": payload["name"],
                    "arguments": payload["arguments_raw"],
                    "tool_call_id": payload["tool_call_id"],
                    "arguments_parsed": payload["arguments"],
                    "reflect_round": reflect_round,
                    "tool_round": payload["tool_round"],
                })
            elif event.kind == "tool_end":
                await emit("tool_call_end", {
                    "name": payload["name"],
                    "arguments": payload["arguments_raw"],
                    "tool_call_id": payload["tool_call_id"],
                    "is_error": payload["is_error"],
                    "reflect_round": reflect_round,
                    "tool_round": payload["tool_round"],
                    "observation": payload["observation"],
                })
            elif event.kind == "result":
                final_content = payload["content"]

        return {"content": final_content}

    # ---------- REFLECT ----------
    async def _reflect(
        self,
        ctx: NodeContext,
        emit: Any,
        llm: Any,
        reflector_prompt: str,
        user_input: str,
        plan_tasks: list[dict[str, Any]],
        execute_output: str,
        usage_total: dict[str, int],
        reflect_round: int,
        model_id: str = "",
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": reflector_prompt},
            {"role": "user", "content": json.dumps({
                "goal": user_input,
                "plan": plan_tasks,
                "execution_result": execute_output,
            }, ensure_ascii=False)},
        ]
        await emit("prompt_text", {
            "phase": "reflect",
            "reflect_round": reflect_round,
            "messages": _messages_for_trace(messages),
        })
        chat_kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
        if model_id:
            chat_kwargs["model"] = model_id
        try:
            resp = await llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reflect 阶段 LLM 调用失败: %s", exc)
            return {"done": True, "critique": f"reflect LLM 失败：{exc}"}
        accumulate_usage(usage_total, resp.usage)
        reflect_text = getattr(resp, "content", "") or ""
        await emit("prompt_text", {
            "phase": "reflect",
            "reflect_round": reflect_round,
            "role": "assistant",
            "content": reflect_text,
        })
        parsed = _safe_json(reflect_text)
        if not isinstance(parsed, dict):
            return {"done": True, "critique": "reflect 输出无法解析，直接收尾"}
        return parsed

    # ---------- 消息组装 ----------
    @staticmethod
    def _build_execution_messages(
        system_prompt: str,
        user_input: str,
        plan_tasks: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        system = system_prompt or "你是一个能干的助手。"
        if plan_tasks:
            system = f"{system}\n\n任务清单：{json.dumps(plan_tasks, ensure_ascii=False)}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # 20261106 P3：chat 兼容通道的多轮历史，拼接位置与旧 chat 通道一致
        # （system 之后、当前问题之前），且同样只保留 user/assistant 非空内容
        for item in history or []:
            role = str(item.get("role") or "")
            content = item.get("content") or ""
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
        messages.append({"role": "user", "content": user_input})
        return messages


# ---------- helpers ----------
def _safe_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # 兼容模型输出 ```json ... ``` 包裹
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None


def _resolve_run_context(raw: Any) -> Any:
    """还原 chat 兼容通道传入的运行上下文（20261106 review 修正）。

    画布入参会进 run 表 JSONB 与 graph state，只能是 json.dumps 可序列化形态，
    因此 chat 侧传 AgentRunContext.to_storage_dict() 平铺字典，这里还原为对象；
    已是 AgentRunContext 实例（进程内直调/测试）时原样透传，非法字典返回 None。
    """
    if isinstance(raw, dict):
        return AgentRunContext.from_storage_dict(raw)
    return raw


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


TRACE_MESSAGE_CONTENT_LIMIT = 4000


def _messages_for_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 messages 精简到前端可展示的形态：tool_calls 去掉冗余 schema，长 content 截断。"""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if len(content) > TRACE_MESSAGE_CONTENT_LIMIT:
            content = content[:TRACE_MESSAGE_CONTENT_LIMIT] + f"... [truncated {len(content)} chars]"
        item: dict[str, Any] = {"role": role, "content": content}
        if m.get("tool_calls"):
            item["tool_calls"] = [
                {
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments"),
                }
                for tc in m["tool_calls"]
            ]
        if m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        out.append(item)
    return out


register_node_handler(AgentLoopNodeHandler())
