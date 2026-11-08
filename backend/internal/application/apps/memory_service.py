"""记忆执行服务（M4 PRD F15.4/F15.5 摘要 + F16.3 长期记忆抽取，20261107）。

MemorySummarizerService：把 plan_summarization 产出的待压缩段 + 旧摘要交给 LLM
增量合并，成功后按乐观并发回写 conversation 摘要水位线（update_summary_if_marker）。
失败契约（F15.5）：模型解析失败 / LLM 异常超时 / 空产出 / 回写让位一律返回
None 并记 warning，绝不抛出——调用方沿用旧摘要 + truncate 组合，摘要链路
不得阻塞对话主流程。兜底面为不可预测的网络/网关异常故捕获 Exception，
但均记录日志与上下文，不做静默吞异常处理。

MemoryExtractorService：轮后异步（Celery）从单轮对话抽取长期记忆，对照现有
活跃记忆由同一次 LLM 调用给出 add/update/delete 合并指令（F16.3）。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from internal.application.apps.model_service import ModelService
from internal.domain.agent.memory import (
    SummarizationPlan,
    parse_extract_ops,
    parse_long_term_config,
)
from internal.domain.agent.prompt import EXTRACT_PROMPT, SUMMARY_PROMPT
from internal.domain.canvas.convert import find_agent_loop_config
from internal.domain.repository.apps_protocols import ConversationRepositoryProtocol

logger = logging.getLogger(__name__)


class MemorySummarizerService:
    """摘要式记忆的执行体：LLM 增量合并 + 水位线乐观回写（配置解析/计划判定在 domain 层）。"""

    def __init__(
        self,
        model_service: ModelService,
        conv_repo: ConversationRepositoryProtocol,
    ) -> None:
        """依赖由组合根注入（web.deps/apps_services），本服务不自行构造 infra 具体类。"""
        self._model_service = model_service
        self._conv_repo = conv_repo

    async def refresh_summary(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        plan: SummarizationPlan,
        old_summary: str | None,
        watermark_id: Any,
        memory: dict[str, Any],
        default_model_id: str,
    ) -> str | None:
        """执行摘要合并并回写；返回生效的新摘要正文，None = 本轮无更新（降级）。

        契约：调用方需已完成 plan_summarization 判定；should_summarize=False 时
        本方法直接返回 None（不发起 LLM 调用，频控收口在纯函数侧）。
        """
        if not plan.should_summarize or not plan.to_compress:
            return None
        model_id = str(memory.get("summarizeModel") or "").strip() or default_model_id
        max_chars = int(memory.get("maxSummaryChars") or 0) or None
        try:
            client = self._model_service.get_client_for_tenant(model_id, tenant_id)
        except Exception as exc:
            logger.warning(
                "摘要模型解析失败，跳过本轮摘要 conversation_id=%s model=%s: %s",
                conversation_id,
                model_id,
                exc,
            )
            return None

        messages = self._build_messages(plan, old_summary, max_chars)
        try:
            response = await client.chat(
                messages=messages,
                temperature=0,
                max_tokens=self._output_token_cap(max_chars),
            )
        except Exception as exc:
            logger.warning(
                "摘要 LLM 调用失败，降级旧摘要+truncate conversation_id=%s: %s",
                conversation_id,
                exc,
            )
            return None

        summary = (response.content or "").strip()
        if not summary:
            logger.warning("摘要产出为空，跳过回写 conversation_id=%s", conversation_id)
            return None
        if max_chars and len(summary) > max_chars:
            summary = summary[:max_chars]

        written = self._conv_repo.update_summary_if_marker(
            conversation_id,
            old_marker=watermark_id,
            summary=summary,
            new_marker=plan.new_marker,
        )
        if not written:
            logger.info("摘要水位线已被并发轮次前移，本轮让位 conversation_id=%s", conversation_id)
            return None
        return summary

    @staticmethod
    def _build_messages(
        plan: SummarizationPlan, old_summary: str | None, max_chars: int | None
    ) -> list[dict[str, Any]]:
        """组装增量合并提示：已有摘要 + 新增对话两段式（模板见 SUMMARY_PROMPT）。"""
        dialog = "\n".join(f"{item['role']}: {item['content']}" for item in plan.to_compress)
        user_content = (
            f"【已有摘要】\n{(old_summary or '').strip() or '（无）'}\n\n【新增对话】\n{dialog}"
        )
        system_prompt = SUMMARY_PROMPT.format(max_chars=max_chars or 1500)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _output_token_cap(max_chars: int | None) -> int | None:
        """按配置字数折算输出上限，未配置则交由网关默认。

        review 修正：摘要输出以中文为主（主流分词器约 1 token/字），若按
        estimate_tokens 的 len//2 口径折半，中文摘要会在网关侧被截断成配置
        值的一半长度；按 max_chars + 收尾余量取上限（对英文偏松但无害）。
        """
        if not max_chars:
            return None
        return max_chars + 16


class MemoryExtractorService:
    """长期记忆抽取执行体（M4 PRD F16.3）：单轮对话 → LLM 对照合并 → agent_memory 落库。

    运行载体是 Celery worker（tasks/memory_tasks.py），依赖由 worker 侧装配注入；
    幂等靠 source_run_id 探测（add 路径；纯 update 轮重试代价由"仅重试 1 次"收口）。
    与摘要链路相反，本服务允许抛异常——worker 侧才有重试与告警语义，对话主流程
    已在投递点解耦（delay 失败仅 warning）。
    """

    # 传给抽取提示词的现有活跃记忆条数上限（对照去重的窗口）
    context_top_n = 20

    def __init__(
        self,
        *,
        model_service: ModelService,
        run_repo: Any,
        msg_repo: Any,
        conv_repo: ConversationRepositoryProtocol,
        memory_repo: Any,
        default_model_id: str,
    ) -> None:
        self._model_service = model_service
        self._run_repo = run_repo
        self._msg_repo = msg_repo
        self._conv_repo = conv_repo
        self._memory_repo = memory_repo
        self._default_model_id = default_model_id

    async def extract_for_run(self, run_id: UUID) -> dict[str, int]:
        """对一轮已落库的对话执行抽取；返回 {added, updated, deleted}，跳过均为 0。"""
        run = self._run_repo.get_run(run_id)
        if run is None:
            logger.warning("记忆抽取跳过：run 不存在 run_id=%s", run_id)
            return {"added": 0, "updated": 0, "deleted": 0}
        if self._memory_repo.exists_by_source_run(run_id):
            logger.info("记忆抽取跳过：run 已抽取过 run_id=%s", run_id)
            return {"added": 0, "updated": 0, "deleted": 0}

        tenant_id = run["tenant_id"]
        application_id = run["workflow_id"]
        user_id = run.get("user_id")
        if user_id is None:
            logger.warning("记忆抽取跳过：run 缺 user_id run_id=%s", run_id)
            return {"added": 0, "updated": 0, "deleted": 0}

        config = self._config_from_run_snapshot(run)
        if config is None:
            return {"added": 0, "updated": 0, "deleted": 0}
        long_term, app_model_id = config
        if not long_term["enabled"]:
            # 配置未开启/画布无 agent_loop：零开销跳过（PRD F16.1 关闭态约束）
            return {"added": 0, "updated": 0, "deleted": 0}

        rows = self._msg_repo.list_messages_by_run(run_id)
        dialog = "\n".join(f"{r['role']}: {r['content']}" for r in rows if r.get("content"))
        if not dialog:
            return {"added": 0, "updated": 0, "deleted": 0}

        existing = self._memory_repo.list_active(
            tenant_id=tenant_id,
            application_id=application_id,
            user_id=user_id,
            limit=self.context_top_n,
        )
        # 抽取模型回退链：longTerm.extractModel → 应用主模型（画布 modleName）→ settings 默认
        client = self._model_service.get_client_for_tenant(
            long_term["extractModel"] or app_model_id or self._default_model_id, tenant_id
        )
        response = await client.chat(
            messages=self._build_messages(rows, existing),
            temperature=0,
        )
        ops = parse_extract_ops(response.content or "")
        counts = {"added": 0, "updated": 0, "deleted": 0}
        for op in ops:
            applied = self._apply_op(op, run_id, tenant_id, application_id, user_id)
            if applied:
                counts[{"add": "added", "update": "updated", "delete": "deleted"}[op["op"]]] += 1
        if counts["added"]:
            self._memory_repo.archive_overflow(
                tenant_id=tenant_id,
                application_id=application_id,
                user_id=user_id,
                max_active=long_term["maxMemories"],
            )
        if any(counts.values()):
            # M4 PRD F16.7：抽取计数回写 run.output（顶层键 additive），admin run
            # 详情可直接观察本轮沉淀结果；全 0 不写，避免无意义覆盖
            self._run_repo.merge_run_output(run_id, {"memory_extract": counts})
        logger.info(
            "记忆抽取完成 run_id=%s added=%s updated=%s deleted=%s",
            run_id,
            counts["added"],
            counts["updated"],
            counts["deleted"],
        )
        return counts

    def _apply_op(
        self, op: dict[str, Any], run_id: UUID, tenant_id: UUID, application_id: UUID, user_id: UUID
    ) -> bool:
        """执行单条抽取指令；id 非法/目标不存在返回 False。"""
        try:
            if op["op"] == "add":
                self._memory_repo.insert(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    user_id=user_id,
                    kind=op["kind"],
                    content=op["content"],
                    source_run_id=run_id,
                    metadata={"source": "extract"},
                )
                return True
            target_id = UUID(str(op["memory_id"]))
            if op["op"] == "update":
                return self._memory_repo.update_content(
                    target_id, content=op["content"], kind=op["kind"]
                )
            return self._memory_repo.delete_scoped(
                target_id, tenant_id=tenant_id, user_id=user_id, application_id=application_id
            )
        except (ValueError, TypeError):
            logger.warning("记忆抽取指令目标 id 非法 run_id=%s op=%s", run_id, op)
            return False

    def _build_messages(self, rows: list[dict], existing: list[dict]) -> list[dict[str, Any]]:
        """system=EXTRACT_PROMPT；user=更早摘要尾+本轮对话+现有记忆 id 清单。"""
        conversation_id = rows[0].get("conversation_id")
        summary_tail = ""
        if conversation_id is not None:
            conv = self._conv_repo.get_conversation(conversation_id) or {}
            summary_tail = str(conv.get("summary") or "")
        existing_lines = (
            "\n".join(f"- memory_id={r['id']} [{r['kind']}] {r['content']}" for r in existing)
            or "（无）"
        )
        user_content = (
            f"【更早对话摘要】\n{summary_tail or '（无）'}\n\n"
            f"【本轮对话】\n" + "\n".join(f"{r['role']}: {r['content']}" for r in rows) + "\n\n"
            f"【现有记忆】\n{existing_lines}"
        )
        return [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _config_from_run_snapshot(
        self, run: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None] | None:
        """从本轮 run 的画布快照读 longTerm 配置（与运行时同源口径，review 修正）。

        worker 不再二次解析 graph 版本（发布→最新/pin 覆盖），直接采用 ensure_run
        落库的 graph_snapshot：对话按哪版执行，抽取就按哪版判定开关与模型，
        杜绝配置面改版后"对话与抽取各按一版"的漂移；快照缺失/无 agent_loop
        按未启用处理（返回 None，本轮零沉淀）。
        """
        graph = run.get("graph_snapshot")
        if isinstance(graph, str):
            try:
                graph = json.loads(graph)
            except ValueError:
                return None
        if not isinstance(graph, dict):
            return None
        found = find_agent_loop_config(graph)
        if found is None:
            return None
        node_cfg = found[1]
        long_term = parse_long_term_config(node_cfg.get("memory"))
        app_model_id = (
            str(node_cfg.get("modleName") or node_cfg.get("modelName") or "").strip() or None
        )
        return long_term, app_model_id
