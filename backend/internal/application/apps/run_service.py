"""运行审计应用服务：marketplace 的 run 查询 / 详情 / fork 落记录（DDD 五期从 router 下沉）。

只读方法不提交事务。fork 用的 insert_run 有意不在服务内提交：fork 端点在
runner 续跑结束后统一 uow.commit()，run 记录与 checkpoint 写入保持同一事务边界，
与迁移前行为一致。租户归属校验（get_run_owned）查不到与跨租户统一按不存在处理。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from internal.application.errors import NotFoundError
from internal.domain.repository.apps_protocols import RunRepositoryProtocol


class RunService:
    """run / node_execution 查询与写入编排（不含提交策略见模块 docstring）。"""

    def __init__(self, run_repo: RunRepositoryProtocol) -> None:
        self._repo = run_repo

    def get_running_for_thread(
        self, tenant_id: UUID, application_id: UUID, thread_id: str,
    ) -> dict[str, Any]:
        """取该 thread 等待审批的运行记录；无则按业务错误抛出。"""
        run = self._repo.get_running_by_thread(tenant_id, application_id, thread_id)
        if run is None:
            raise NotFoundError("没有等待审批的运行记录")
        return run

    def list_runs(
        self, tenant_id: UUID, *, workflow_id: UUID | None = None, limit: int = 50,
    ) -> list[dict]:
        """租户查看某应用的运行历史。"""
        return self._repo.list_runs(tenant_id, workflow_id=workflow_id, limit=limit)

    def get_run_owned(self, run_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        """按租户校验 run 归属，查不到或跨租户统一按不存在处理。"""
        run = self._repo.get_run(run_id)
        if run is None or run["tenant_id"] != tenant_id:
            raise NotFoundError("运行记录不存在")
        return run

    def get_run_detail(self, run_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        """run 元信息 + 节点执行列表。"""
        run = self.get_run_owned(run_id, tenant_id)
        return {"run": run, "node_executions": self._repo.list_node_executions(run_id)}

    def insert_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        workflow_id: UUID,
        graph_snapshot: dict[str, Any],
        input_data: dict[str, Any],
        thread_id: str,
        user_id: UUID | None = None,
    ) -> None:
        """fork 前落一条新 run 记录（提交时机由调用端点控制）。"""
        self._repo.insert_run(
            run_id=run_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            graph_snapshot=graph_snapshot,
            input_data=input_data,
            thread_id=thread_id,
            user_id=user_id,
        )
