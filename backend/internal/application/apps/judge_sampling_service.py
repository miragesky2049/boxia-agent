"""M4-d T-d8 F19.3：线上采样 judge 应用服务（worker 侧对已落库 run 异步判定）。

ChatService 在主会话 assistant 消息落库提交后投递 judge_sampling(run_id)；本服务按
该 run 的画布快照判定（与运行时、记忆抽取同源，杜绝配置改版后"对话与采样各按一版"）：
- 采样纯观测不干预回答：结果只落 eval_result(source=runtime_sample) 供看板归因；
- judge 自身 token 计入 tenant_usage_ledger（node_id=judge_sampling），U9 成本可见；
- 幂等由 has_runtime_sample 探测保证：任务重投不重复判定、不重复计费；
- 判定口径信内核 verdict.passed（采样键组无 passScore，内核默认线与默认 rubric
  文案一致；自定义 rubric 时由模型按准则自判）；
- judge 传输层异常上抛，由 Celery 任务层按抽取先例重试 1 次后放弃。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from internal.application.apps.model_service import ModelService
from internal.application.errors import NotFoundError, ValidationError
from internal.domain.agent.judge import judge
from internal.domain.canvas.agent_config import parse_judge_sampling_config
from internal.domain.canvas.convert import find_agent_loop_config
from internal.infrastructure.id.uuid7 import new_uuid

logger = logging.getLogger(__name__)


class JudgeSamplingService:
    """对单个已落库 run 执行采样判定；跳过口径全部返回 None（零写入）。"""

    def __init__(
        self,
        *,
        run_repo: Any,
        msg_repo: Any,
        eval_repo: Any,
        usage_repo: Any,
        model_service: ModelService,
        default_model_id: str,
    ) -> None:
        self._run_repo = run_repo
        self._msg_repo = msg_repo
        self._eval_repo = eval_repo
        self._usage_repo = usage_repo
        self._model_service = model_service
        self._default_model_id = default_model_id

    async def sample_for_run(self, run_id: UUID) -> dict[str, Any] | None:
        """采样判定一轮已落库对话；返回 {"status", "score"}，各跳过口径返回 None。"""
        run = self._run_repo.get_run(run_id)
        if run is None:
            logger.warning("judge 采样跳过：run 不存在 run_id=%s", run_id)
            return None
        if run.get("execute_status") != "success":
            # 挂起/接管/异常终态不判：回答未定型，判定只会污染看板
            return None
        if run.get("is_eval") or run.get("parent_run_id") is not None:
            # 评测批 run 已有 eval_run 通道判定；委派子 run 归因在父 run，不重复计费
            return None
        if self._eval_repo.has_runtime_sample(run_id):
            logger.info("judge 采样跳过：run 已判定过 run_id=%s", run_id)
            return None

        config = self._config_from_run_snapshot(run)
        if config is None:
            return None
        sampling, app_model_id = config
        if not sampling["enabled"]:
            # 快照里采样未开启（投递后配置被关）：按执行当时的版本零开销跳过
            return None

        rows = self._msg_repo.list_messages_by_run(run_id)
        question = next(
            (r["content"] for r in rows if r.get("role") == "user" and r.get("content")), ""
        )
        answer = next(
            (
                r["content"]
                for r in reversed(rows)
                if r.get("role") == "assistant" and r.get("content")
            ),
            "",
        )
        if not question or not answer:
            return None

        tenant_id = run["tenant_id"]
        application_id = run["workflow_id"]
        user_id = run.get("user_id")
        # 模型回退链：judgeModel → 答题模型（画布 modleName）→ settings 默认（抽取先例同构）。
        # 批末 review P2-2：judgeModel 配置了但目录解析失败同样沿链回退（F19.5：模型错配
        # 是配置质量问题，仅 warning，不能让该应用全部采样在重试用尽后静默归零）
        candidates = [
            m for m in (str(sampling["judgeModel"]), app_model_id, self._default_model_id) if m
        ]
        client: Any = None
        model_id = ""
        for candidate in candidates:
            try:
                client = self._model_service.get_client_for_tenant(candidate, tenant_id)
                model_id = candidate
                break
            except (NotFoundError, ValidationError) as exc:
                logger.warning(
                    "judge 采样模型 %s 解析失败，沿回退链降级 run_id=%s: %s", candidate, run_id, exc
                )
        if client is None:
            raise ValidationError(f"judge 采样无可用模型：候选链均解析失败 run_id={run_id}")
        verdict = await judge(
            client,
            model=model_id,
            rubric=sampling["rubric"],
            question=question,
            answer=answer,
        )
        usage = verdict.usage.model_dump()
        if usage["total_tokens"]:
            try:
                self._usage_repo.record_usage(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    run_id=run_id,
                    node_id="judge_sampling",
                    model_id=model_id,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    total_tokens=usage["total_tokens"],
                    user_id=user_id,
                )
            except Exception as exc:  # noqa: BLE001 - 计量旁路失败不阻塞判定落库，仅告警
                logger.warning("judge 采样计量写 ledger 失败 run_id=%s: %s", run_id, exc)

        status = "pass" if verdict.passed else "fail"
        self._eval_repo.insert_results(
            [
                {
                    "id": new_uuid(),
                    "tenant_id": tenant_id,
                    "eval_run_id": None,
                    "run_id": run_id,
                    "case_id": None,
                    "status": status,
                    "score": verdict.score,
                    "reason": verdict.critique,
                    "judge_usage": usage if usage["total_tokens"] else None,
                    "source": "runtime_sample",
                }
            ]
        )
        logger.info(
            "judge 采样完成 run_id=%s status=%s score=%s model=%s",
            run_id,
            status,
            verdict.score,
            model_id,
        )
        return {"status": status, "score": verdict.score}

    def _config_from_run_snapshot(self, run: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        """从 run 画布快照读 judgeSampling 配置与答题模型（与记忆抽取同口径，快照缺失
        /无 agent_loop 返回 None 按未启用处理）。"""
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
        sampling = parse_judge_sampling_config(node_cfg.get("judgeSampling"))
        app_model_id = str(node_cfg.get("modleName") or node_cfg.get("modelName") or "")
        return sampling, app_model_id
