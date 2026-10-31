"""Agent 循环节点（coze agent_loop，本项目 type_code=100）。

独立图协议：plan / execute / reflect 三阶段，非 Dag 节点。

config 约定：
- modleName: 主模型 ID（同 LLM 节点）
- systemPrompt: 系统提示词（agent 角色）
- tools: 向 LLM 暴露的工具 schema（OpenAI tools 数组）
- maxToolRounds: execute 阶段 ReAct 最大轮次（默认 5）
- maxReflectRounds: reflect 最大迭代轮次（默认 3，防止 plan→reflect 死循环）
- plannerPrompt: 可选，plan 阶段系统提示词（默认内置）
- reflectorPrompt: 可选，reflect 阶段系统提示词（默认内置）

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
        user_input = str(ctx.inputs.get("input") or "")

        model_id = _to_str(config.get("modleName") or config.get("modelName"))
        system_prompt = _to_str(config.get("systemPrompt"))
        planner_prompt = _to_str(config.get("plannerPrompt")) or DEFAULT_PLANNER_PROMPT
        reflector_prompt = _to_str(config.get("reflectorPrompt")) or DEFAULT_REFLECTOR_PROMPT
        max_tool_rounds = _to_int(config.get("maxToolRounds")) or DEFAULT_MAX_TOOL_ROUNDS
        max_reflect_rounds = _to_int(config.get("maxReflectRounds")) or DEFAULT_MAX_REFLECT_ROUNDS

        tool_specs = _build_tool_specs(config.get("tools"))
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

        # 1. PLAN
        plan_tasks = await self._plan(ctx, _emit, llm, planner_prompt, user_input, usage_total)

        # 2. EXECUTE / REFLECT 迭代
        execution_messages = self._build_execution_messages(
            system_prompt=system_prompt,
            user_input=user_input,
            plan_tasks=plan_tasks,
        )
        final_answer = ""
        reflect_history: list[dict[str, Any]] = []

        for reflect_round in range(max_reflect_rounds):
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
            )
            final_answer = execute_output["content"]

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
    ) -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_input},
        ]
        await emit("prompt_text", {
            "phase": "plan",
            "messages": _messages_for_trace(messages),
        })
        try:
            resp = await llm.chat(messages=messages, response_format={"type": "json_object"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan 阶段 LLM 调用失败: %s", exc)
            return [{"id": "t1", "goal": user_input, "acceptance": "直接回答用户问题"}]

        _accumulate(usage_total, resp)
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

    # ---------- EXECUTE（ReAct 循环）----------
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
    ) -> dict[str, Any]:
        final_content = ""
        for round_idx in range(max_tool_rounds):
            await emit("prompt_text", {
                "phase": "execute",
                "reflect_round": reflect_round,
                "tool_round": round_idx,
                "messages": _messages_for_trace(messages),
            })
            try:
                kwargs: dict[str, Any] = {"messages": messages}
                if tool_specs:
                    kwargs["tools"] = tool_specs
                resp = await llm.chat(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("execute 阶段 LLM 调用失败: %s", exc)
                final_content = f"[execute error] {exc}"
                break

            _accumulate(usage_total, resp)
            content = getattr(resp, "content", "") or ""
            tool_calls = list(getattr(resp, "tool_calls", None) or [])

            await emit("prompt_text", {
                "phase": "execute",
                "reflect_round": reflect_round,
                "tool_round": round_idx,
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in tool_calls
                ],
            })

            if not tool_calls:
                final_content = content
                break

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                call_payload = {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                    "reflect_round": reflect_round,
                    "tool_round": round_idx,
                }
                await emit("tool_call_start", call_payload)
                observation = await _run_tool(tool_executor, tc.function.name, tc.function.arguments)
                await emit("tool_call_end", {**call_payload, "observation": observation})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": observation,
                })
        else:
            final_content = "（execute 达到最大工具轮次）"

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
        try:
            resp = await llm.chat(messages=messages, response_format={"type": "json_object"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("reflect 阶段 LLM 调用失败: %s", exc)
            return {"done": True, "critique": f"reflect LLM 失败：{exc}"}
        _accumulate(usage_total, resp)
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
    ) -> list[dict[str, Any]]:
        system = system_prompt or "你是一个能干的助手。"
        if plan_tasks:
            system = f"{system}\n\n任务清单：{json.dumps(plan_tasks, ensure_ascii=False)}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_input},
        ]


# ---------- helpers ----------
def _build_tool_specs(tools_raw: Any) -> list[LLMToolSpec]:
    if not tools_raw or not isinstance(tools_raw, list):
        return []
    specs: list[LLMToolSpec] = []
    for item in tools_raw:
        if isinstance(item, LLMToolSpec):
            specs.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("function", {}).get("name")
        if not name:
            continue
        description = item.get("description") or item.get("function", {}).get("description", "")
        parameters = item.get("parameters") or item.get("function", {}).get("parameters") or {
            "type": "object", "properties": {},
        }
        specs.append(LLMToolSpec(name=str(name), description=str(description), parameters=parameters))
    return specs


async def _run_tool(executor: Any, name: str, raw_arguments: str) -> str:
    if executor is None:
        return f"[error] 工具未注册: {name}"
    args = _parse_args(raw_arguments)
    try:
        result = executor(name, args)
        if hasattr(result, "__await__"):
            result = await result
        return str(result)
    except Exception as exc:  # noqa: BLE001
        return f"[error] {name}: {exc}"


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    except (json.JSONDecodeError, ValueError):
        return {"input": str(raw or "")}


def _accumulate(aggregated: dict[str, int], resp: Any) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    aggregated["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
    aggregated["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
    aggregated["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)


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
