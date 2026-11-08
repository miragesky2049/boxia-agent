"""M4-d T-d3：EvalRunService —— 评测批任务（PRD F18.4）。

start_batch 落 eval_run 行并投递 Celery（投递失败降级为 error 态、发起接口不炸）；
run_batch 在 worker 内逐 case 直调图快照、执行评估器断言、回写进度与汇总。
并发入参现阶段只做记录与 clamp（2~4），主协程串行执行保证进度单调与单 session
串行写；真并发留待容量需求出现时再引入（不为假设需求做设计）。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from internal.domain.agent.judge import DEFAULT_PASS_SCORE, judge
from internal.domain.agent.prompt import JUDGE_RUBRIC_DEFAULT
from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository

logger = logging.getLogger(__name__)

# 并发上限 clamp：worker 单容器并发与下游模型限流的保守折中（评测场景默认 2）
DEFAULT_CONCURRENCY = 2
MIN_CONCURRENCY = 2
MAX_CONCURRENCY = 4

# 终态 output 中答案文本的候选键，口径对齐 agent_tool_service 的 _ANSWER_TEXT_KEYS
_ANSWER_TEXT_KEYS = ("output", "content", "answer", "text")

# runtime_factory 契约：(case, tenant_id, application_id, graph_version) -> runner
# runner 需具备 run_id 属性与 async invoke(input_data) -> output
RuntimeFactory = Callable[..., Awaitable[Any]]


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def extract_answer_text(output: Any) -> str:
    """从图终态提取待评答案文本；无文本键时整体序列化兜底。"""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in _ANSWER_TEXT_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(output, ensure_ascii=False)
    return "" if output is None else str(output)


def _question_of(case: dict[str, Any]) -> str:
    input_data = case.get("input") or {}
    if isinstance(input_data, dict):
        message = input_data.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(input_data, ensure_ascii=False)
    return str(input_data)


def _trace_problem(expected: dict[str, Any] | None, trace_names: set[str]) -> str:
    """case 级工具轨迹断言（F18.2 expected_tool_calls），独立于评估器先行判定。"""
    if not expected:
        return ""
    problems: list[str] = []
    for tool in expected.get("must_call") or []:
        if tool not in trace_names:
            problems.append(f"必需调用工具未出现: {tool}")
    for tool in expected.get("must_not_call") or []:
        if tool in trace_names:
            problems.append(f"禁调工具被调用: {tool}")
    return "; ".join(problems)


def _rule_verdict(config: dict[str, Any], answer: str) -> tuple[bool, int, str]:
    """rule 评估器断言：contains/notContains/regex/jsonSchema，全不配置视为恒过。

    jsonSchema 为轻量口径：仅校验"可解析且为 JSON 对象"，不做 schema 表达式断言
    （完整 schema 校验属容量需求出现时再引入 jsonschema 库，批末 review#10 记录）。
    """
    problems: list[str] = []
    contains = config.get("contains")
    if contains and contains not in answer:
        problems.append(f"缺少必需文本: {contains}")
    not_contains = config.get("notContains")
    if not_contains and not_contains in answer:
        problems.append(f"包含禁现文本: {not_contains}")
    pattern = config.get("regex")
    if pattern:
        try:
            if re.search(pattern, answer) is None:
                problems.append("正则未命中")
        except re.error as exc:
            # 评估器配置错误记为该断言失败而非抛出：不能中断整批其余 case
            problems.append(f"正则非法: {exc}")
    if config.get("jsonSchema"):
        try:
            parsed = json.loads(answer)
        except ValueError:
            problems.append("输出不是可解析 JSON")
        else:
            if not isinstance(parsed, dict):
                problems.append("输出不是 JSON 对象")
    passed = not problems
    return passed, 10 if passed else 0, "; ".join(problems)


def _judge_rubric(config: dict[str, Any]) -> str:
    """judge 评分准则文本：passScore 融进准则文案（阈值业务语义归消费方，F19.5）。"""
    rubric = str(config.get("rubric") or "").strip() or JUDGE_RUBRIC_DEFAULT
    pass_score = config.get("passScore")
    if pass_score is not None:
        rubric = f"{rubric}\n通过分：{pass_score}/10"
    return rubric


class EvalRunService:
    """评测批任务应用服务：发起（start_batch）与执行（run_batch）两段。"""

    def __init__(
        self,
        *,
        eval_repo: EvalRepository,
        run_repo: RunRepository,
        runtime_factory: RuntimeFactory | None,
        judge_llm_factory: Callable[[str], Any] | None = None,
        batch_task: Any = None,
        commit_hook: Callable[[], None] | None = None,
    ) -> None:
        self._eval_repo = eval_repo
        self._run_repo = run_repo
        self._runtime_factory = runtime_factory
        self._judge_llm_factory = judge_llm_factory
        self._batch_task = batch_task
        self._commit_hook = commit_hook
        # M4-d F19.5/T-d7：judge 客户端按模型缓存（键=config.model，空串=全局默认）；
        # 只在批内确实有 llm_judge 评估器时才付出模型构造成本
        self._judge_llms: dict[str, Any] = {}

    def start_batch(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        dataset_id: UUID,
        graph_version: int,
        evaluator_ids: list[str],
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> UUID:
        """登记批任务并投递 worker；返回 eval_run id（前端轮询进度用）。

        同步方法：内部全是同步 DB 与 broker 投递，若写成 async 会占住事件循环
        （批末 review#3：broker 不可达时 .delay() 阻塞到超时）。
        """
        if tenant_id is None or application_id is None or dataset_id is None:
            raise ValueError("tenant_id / application_id / dataset_id 均不能为空")
        if graph_version is None or graph_version <= 0:
            raise ValueError("graph_version 必须为正整数")
        run_id = new_uuid()
        clamped = max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, concurrency))
        self._eval_repo.insert_eval_run(
            run_id=run_id,
            tenant_id=tenant_id,
            application_id=application_id,
            graph_version=graph_version,
            dataset_id=dataset_id,
            evaluator_ids=[str(eid) for eid in evaluator_ids or []],
        )
        self._eval_repo.update_eval_run(run_id, progress={"concurrency": clamped})
        # 先提交再投递：worker 可能立即消费，未提交行会让它查不到任务现场
        self._flush()
        if self._batch_task is not None:
            try:
                self._batch_task.delay(str(tenant_id), str(run_id))
            except Exception as exc:  # noqa: BLE001 - 旁路投递失败绝不升级为发起接口错误（对齐记忆抽取投递先例）
                logger.warning("评测批任务投递失败 eval_run=%s：%s", run_id, exc)
                self._eval_repo.update_eval_run(
                    run_id, status="error", error_message=f"投递失败: {exc}"[:500]
                )
                self._flush()
        return run_id

    async def run_batch(self, tenant_id: UUID, eval_run_id: UUID) -> None:
        """执行整批评测（worker 入口）：逐 case 直调、判定、回写进度。"""
        if tenant_id is None or eval_run_id is None:
            raise ValueError("tenant_id / eval_run_id 均不能为空")
        run = self._eval_repo.get_eval_run(tenant_id, eval_run_id)
        if run is None:
            logger.warning("评测批任务不存在 eval_run=%s", eval_run_id)
            return
        if run["status"] != "running":
            # 幂等守卫（批末 review#1）：task_acks_late 下已终态批可能被 broker
            # 重投，重放会重复计数与重复计费，直接跳过
            logger.warning(
                "评测批任务非 running 态，跳过重投 eval_run=%s status=%s",
                eval_run_id,
                run["status"],
            )
            return
        if self._runtime_factory is None:
            self._eval_repo.update_eval_run(
                eval_run_id, status="error", error_message="未注入 runtime_factory"
            )
            self._flush()
            return
        # 中途被杀的重投（状态仍 running）清理上次部分落库的结果行，从头重放
        self._eval_repo.delete_results(eval_run_id)
        self._flush()
        try:
            await self._execute(tenant_id, run)
        except Exception as exc:  # noqa: BLE001 - 批任务必须落终态，未预期异常统一置 error 供页面可见
            logger.exception("评测批任务异常终止 eval_run=%s", eval_run_id)
            self._eval_repo.update_eval_run(
                eval_run_id, status="error", error_message=str(exc)[:500]
            )
            self._flush()

    async def _execute(self, tenant_id: UUID, run: dict[str, Any]) -> None:
        eval_run_id = run["id"]
        cases = self._eval_repo.list_cases(tenant_id, run["dataset_id"])
        selected = {str(eid) for eid in run["evaluator_ids"] or []}
        evaluators = [
            ev for ev in self._eval_repo.list_evaluators(tenant_id) if str(ev["id"]) in selected
        ]
        progress: dict[str, int] = {
            "total": len(cases),
            "done": 0,
            "passed": 0,
            "failed": 0,
            "errored": 0,
        }
        usage_total = _zero_usage()
        for case in cases:
            row, case_status, case_usage = await self._run_case(tenant_id, run, case, evaluators)
            self._eval_repo.insert_results([row])
            progress["done"] += 1
            if case_status == "pass":
                progress["passed"] += 1
            elif case_status == "fail":
                progress["failed"] += 1
            else:
                progress["errored"] += 1
            for key in usage_total:
                usage_total[key] += case_usage.get(key, 0)
            # 逐 case 心跳：页面轮询进度条；done 单调递增
            self._eval_repo.update_eval_run(eval_run_id, progress=dict(progress))
            self._flush()
        final_kwargs: dict[str, Any] = {"status": "completed", "progress": dict(progress)}
        if usage_total["total_tokens"]:
            # F18.4：eval_run.usage 只汇总 judge 自身开销；被评 run 的 token 已随
            # record_usage 入 ledger（U9 归因经 run.is_eval），不重复计费
            final_kwargs["usage"] = usage_total
        self._eval_repo.update_eval_run(eval_run_id, **final_kwargs)
        self._flush()

    async def _run_case(
        self,
        tenant_id: UUID,
        run: dict[str, Any],
        case: dict[str, Any],
        evaluators: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str, dict[str, int]]:
        """单 case：直调图 → 轨迹断言 → 评估器逐一打分 → 汇总为一行 eval_result。"""
        factory = self._runtime_factory
        if factory is None:
            # 防御性收口：run_batch 入口已校验，此处同时给类型检查器收窄
            raise RuntimeError("未注入 runtime_factory，无法执行评测 case")
        runner = await factory(case, tenant_id, run["application_id"], run["graph_version"])
        try:
            output = await runner.invoke(case["input"])
        except Exception as exc:  # noqa: BLE001 - 单 case 失败记 error 行、不中断整批（F18.4）
            logger.warning("评测 case 执行失败 case=%s：%s", case["id"], exc)
            # error 行 run_id 置 NULL：图构建阶段异常时 run 行可能尚未落库，写入反而违反外键
            row = self._build_row(
                tenant_id=tenant_id,
                eval_run_id=run["id"],
                run_id=None,
                case=case,
                status="error",
                score=None,
                reason=str(exc),
                judge_usage=None,
            )
            return row, "error", _zero_usage()

        answer = extract_answer_text(output)
        trace_names = self._collect_trace_names(output, getattr(runner, "run_id", None))
        verdict_lines: list[str] = []
        scores: list[int] = []
        all_passed = True
        case_usage = _zero_usage()

        trace_problem = _trace_problem(case.get("expected_tool_calls"), trace_names)
        if trace_problem:
            all_passed = False
            verdict_lines.append(trace_problem)

        for evaluator in evaluators:
            passed, score, reason, usage = await self._evaluate_one(evaluator, case, answer)
            scores.append(score)
            for key in case_usage:
                case_usage[key] += (usage or {}).get(key, 0)
            if not passed:
                all_passed = False
                verdict_lines.append(reason or f"评估器「{evaluator['name']}」断言失败")

        status = "pass" if all_passed else "fail"
        # 得分口径：各评估器同尺（0~10）取均值四舍五入；无评估器时不落分
        score_value = round(sum(scores) / len(scores)) if scores else None
        row = self._build_row(
            tenant_id=tenant_id,
            eval_run_id=run["id"],
            run_id=getattr(runner, "run_id", None),
            case=case,
            status=status,
            score=score_value,
            reason="; ".join(verdict_lines),
            judge_usage=case_usage if case_usage["total_tokens"] else None,
        )
        return row, status, case_usage

    async def _evaluate_one(
        self, evaluator: dict[str, Any], case: dict[str, Any], answer: str
    ) -> tuple[bool, int, str, dict[str, int]]:
        config = evaluator.get("config") or {}
        if evaluator["type"] == "llm_judge":
            # M4-d T-d7：评估器级 judgeModel 端到端解析（config.model 指定的模型
            # 真正用于打分；此前恒用全局默认，模型只作归因文案）
            judge_llm = self._judge_client_for(str(config.get("model") or ""))
            if judge_llm is None:
                return False, 0, f"评估器「{evaluator['name']}」缺少 judge 模型客户端", {}
            try:
                verdict = await judge(
                    judge_llm,
                    model=str(config.get("model") or ""),
                    rubric=_judge_rubric(config),
                    question=_question_of(case),
                    answer=answer,
                    context_refs=[case["expected"]] if case.get("expected") else None,
                )
            except Exception as exc:  # noqa: BLE001
                # 批末 review P2-4：judge 模型传输层异常不得炸整批——记该 case 的
                # fail 行并附异常摘要（与运行时质量门 fail-open 同容错口径）
                logger.warning(
                    "eval judge 调用异常 evaluator=%s: %s", evaluator["name"], exc, exc_info=True
                )
                return False, 0, f"评估器「{evaluator['name']}」judge 调用失败：{exc}"[:200], {}
            # 批末 review：判定线与运行时质量门同源——本消费方按 passScore 自判，
            # 不信内核默认 7 兜底或模型拼写的 passed（passScore 脏值回内核常量）
            threshold = config.get("passScore")
            if isinstance(threshold, bool) or not isinstance(threshold, int):
                threshold = DEFAULT_PASS_SCORE
            passed = verdict.score >= threshold
            reason = "" if passed else f"{evaluator['name']}：{verdict.critique}"
            return passed, verdict.score, reason, verdict.usage.model_dump()
        passed, score, reason = _rule_verdict(config, answer)
        return passed, score, reason, {}

    def _collect_trace_names(self, output: Any, run_id: UUID | None) -> set[str]:
        traces: Any = output.get("tool_traces") if isinstance(output, dict) else None
        if traces is None and run_id is not None:
            # 终态未带工具轨迹时回落 run_node_execution（工具类节点把轨迹记在节点 output）
            traces = [
                trace
                for node in self._run_repo.list_node_executions(run_id)
                if isinstance(node.get("output"), dict)
                for trace in (node["output"].get("tool_traces") or [])
            ]
        names: set[str] = set()
        for trace in traces or []:
            if isinstance(trace, dict):
                name = trace.get("name") or trace.get("tool")
                if name:
                    names.add(str(name))
        return names

    def _build_row(
        self,
        *,
        tenant_id: UUID,
        eval_run_id: UUID,
        run_id: UUID | None,
        case: dict[str, Any],
        status: str,
        score: int | None,
        reason: str,
        judge_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        return {
            "id": new_uuid(),
            "tenant_id": tenant_id,
            "eval_run_id": eval_run_id,
            "run_id": run_id,
            "case_id": case["id"],
            "status": status,
            "score": score,
            "reason": reason,
            "judge_usage": judge_usage,
            "source": "eval_run",
        }

    def _judge_client_for(self, model_id: str) -> Any:
        """按评估器 config.model 解析 judge 客户端；空串 = 未指定，由工厂回退全局默认。

        同模型批内缓存只解析一次（工厂返回 None 也缓存，避免每条 case 重试构造）。
        """
        if self._judge_llm_factory is None:
            return None
        if model_id not in self._judge_llms:
            self._judge_llms[model_id] = self._judge_llm_factory(model_id)
        return self._judge_llms[model_id]

    def _flush(self) -> None:
        if self._commit_hook is not None:
            self._commit_hook()
