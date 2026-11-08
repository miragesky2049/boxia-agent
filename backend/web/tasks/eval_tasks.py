"""Celery 异步任务：评测批执行（M4-d PRD F18.4，20261108）。

发起接口 start_batch 落 eval_run 行并提交后投递 run_batch(tenant_id, eval_run_id)；
worker 进程自建 UoW（先例 memory_tasks），逐 case 经 build_runner 锁定
graph_version 发布快照直调，run 行带 is_eval=true 归因。
重试契约：EvalRunService.run_batch 内部已兜底把批落 completed/error 终态，本层
只兜装配段异常并回写 error；不再整批重投——重跑等于重复计费与重复结果行。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from uuid import UUID

from internal.application.apps.eval_run_service import EvalRunService
from internal.application.apps.model_service import ModelService
from internal.infrastructure.celery_app import celery_app
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.eval_repository import EvalRepository
from internal.infrastructure.repository.apps.model_repository import ModelRepository
from internal.infrastructure.repository.apps.run_repository import RunRepository
from web.deps.apps_services import make_application_service
from web.deps.graph import build_runner

logger = logging.getLogger(__name__)

# worker 进程内复用同一常驻事件循环：AsyncPostgresSaver 是进程级单例
# （domain/graph/checkpoint.py），其 psycopg 连接绑定创建时的 loop；若每个任务
# 各自 asyncio.run 建/销循环，第二批评测会复用死连接报 "the connection is closed"
# （20261108 端点真机冒烟第二批命中）。web 侧单进程单循环不受此影响。
_LOOP: asyncio.AbstractEventLoop | None = None


def _persistent_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        # Windows 上 psycopg async 不兼容 ProactorEventLoop，建循环前切 Selector
        # （先例 web/app_user.py 头部；放在这里而非模块顶层，是避免 admin 端 import
        # 本模块的测试进程被全局改 policy，殃及依赖子进程的 code_node 沙箱——批末
        # review 附带发现）。Linux 部署无此分支。
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


class _CaseInputRunner:
    """case.input → 图 invoke 入参形态适配（agent 图口径见 agent_tool_service）。"""

    def __init__(self, runtime: Any, application_id: UUID) -> None:
        self._runtime = runtime
        self._application_id = application_id

    @property
    def run_id(self) -> Any:
        return self._runtime.run_id

    async def invoke(self, case_input: dict[str, Any]) -> dict[str, Any]:
        message = case_input.get("message") if isinstance(case_input, dict) else None
        graph_input: dict[str, Any] = {"input": str(message or "")}
        if isinstance(case_input, dict):
            if case_input.get("images"):
                graph_input["images"] = case_input["images"]
            if isinstance(case_input.get("inputs"), dict):
                graph_input.update(case_input["inputs"])
        # workflow_chain 放本应用：评测直调与被委派运行同防护语义（F14.5 环路防护）
        graph_input["workflow_chain"] = [str(self._application_id)]
        return await self._runtime.invoke(graph_input)


def _build_service(uow: SqlAlchemyUnitOfWork, eval_run_id: UUID) -> EvalRunService:
    """worker 侧装配：case 直调 runner 工厂 + judge 客户端懒构造 + 逐 case commit_hook。"""
    session = uow.session
    app_service = make_application_service(uow)
    model_service = ModelService(ModelRepository(session))

    async def _factory(case: dict, tenant_id: UUID, application_id: UUID, graph_version: int):
        runner = await build_runner(
            app_service,
            uow,
            None,  # context：Agent/WorkflowToolService 仅透传不访问，评测顶层无上游 ctx
            tenant_id=tenant_id,
            application_id=application_id,
            # thread 按批评隔：同一 case 跨批复跑（版本 A/B 对比）不能继承上一批
            # checkpoint 对话历史，否则第二次评测带着一轮旧上下文答题
            thread_id=f"eval-{eval_run_id}-{case['id']}",
            current_user_id=None,
            graph_version=graph_version,
            is_eval=True,
        )
        return _CaseInputRunner(runner, application_id)

    def _judge_llm_factory(model_id: str = ""):
        # F19.5/T-d7：评估器 config.model 缺省走 settings 默认模型；指定时经
        # resolve_judge_client 按目录解析（解析失败仅 warning 回退默认，不打断批）。
        # 默认模型本身解析失败仍在此抛出，由 run_batch 落 error 态供页面可见
        default_client = model_service.get_client(get_settings().llm_model_id)
        return model_service.resolve_judge_client(model_id, default_client)

    return EvalRunService(
        eval_repo=EvalRepository(session),
        run_repo=RunRepository(session),
        runtime_factory=_factory,
        judge_llm_factory=_judge_llm_factory,
        commit_hook=uow.commit,
    )


@celery_app.task(name="eval.run_batch", bind=True)
def run_batch(self, tenant_id: str, eval_run_id: str) -> None:  # noqa: ANN001 - celery bind 注入 self
    """执行一整批评测直调与判定（进度经 eval_run.progress 心跳透出）。"""
    try:
        uow = SqlAlchemyUnitOfWork()
    except Exception as exc:  # noqa: BLE001 - 数据库会话都建不起来，只能记日志放弃
        logger.error("评测批任务无法启动（数据库不可用）eval_run=%s: %s", eval_run_id, exc)
        return
    try:
        # worker 无请求态：裸 SQL 仓储按 tenant_id 硬条件访问，无需角色过滤（memory_tasks 同构）
        uow.apply_scope((), apply_role_filter=False)
        service = _build_service(uow, UUID(eval_run_id))
        _persistent_loop().run_until_complete(service.run_batch(UUID(tenant_id), UUID(eval_run_id)))
    except Exception as exc:  # noqa: BLE001 - run_batch 内部已兜底终态；走到这里属装配段异常
        logger.exception("评测批任务装配失败 eval_run=%s", eval_run_id)
        try:
            EvalRepository(uow.session).update_eval_run(
                UUID(eval_run_id), status="error", error_message=f"worker 装配失败: {exc}"[:500]
            )
            uow.commit()
        except Exception:  # noqa: BLE001 - 数据库同样不可达时仅留日志，批停在 running 供人工排查
            logger.exception("评测批 error 态回写失败 eval_run=%s", eval_run_id)
    finally:
        uow.close()
