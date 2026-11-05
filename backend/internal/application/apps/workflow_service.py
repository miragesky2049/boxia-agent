"""用户端 workflow 应用服务：schema 提取、流式运行、人审续跑、运行历史与待审批。

与 ChatService 的分工：
- ChatService 管 chat/对话流（会话消息驱动），保留旧的非流式 run_workflow；
- 本服务服务 workflow 形态：表单入参、SSE 节点轨迹、run 审计、人审审批。

所有 4xx 预检（可见性/flow_type/入参/审批角色）都在返回 StreamingResponse 之前完成，
保证鉴权与参数错误走 JSON 而不是 SSE error 事件。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.application.apps.application_service import ApplicationService
from internal.application.apps.ports import RunnerFactory
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.graph.runtime import GraphInterrupted
from internal.domain.repository.apps_protocols import RunRepositoryProtocol
from internal.domain.repository.protocols import UnitOfWork

logger = logging.getLogger(__name__)

# chatflow 专属内置参数：workflow 形态即使被脏写入画布也不能出现在入参 schema 里
BUILTIN_START_PARAMS = {"USER_INPUT", "CONVERSATION_NAME", "CONVERSATION_ID"}
# 问答节点在 workflow 中没有恢复通道，禁止运行
QUESTION_NODE_TYPE = "18"
HUMAN_APPROVAL_NODE_TYPE = "60"

_TYPE_LABELS: dict[str, str] = {
    "string": "文本",
    "number": "数字",
    "boolean": "布尔",
    "object": "对象",
    "file": "文件",
    "image": "图片",
    "array[string]": "文本数组",
    "array[number]": "数字数组",
    "array[object]": "对象数组",
}


@dataclass(frozen=True)
class WorkflowPreparedRun:
    """流外预检通过后的运行上下文。"""

    application_id: UUID
    canvas_json: dict[str, Any]
    inputs: dict[str, Any]
    thread_id: str | None
    schema_inputs: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkflowPreparedResume:
    """续跑预检通过后的上下文（run 必须处于 interrupted 且角色匹配）。"""

    application_id: UUID
    thread_id: str
    run_id: UUID
    approved: bool
    comment: str
    interrupt_payload: dict[str, Any]


def extract_start_inputs(canvas_json: dict[str, Any]) -> list[dict[str, Any]]:
    """从 coze IR 提取 START 手动入参，过滤对话流内置参数，按名称去重。

    手动参数的标准位置是 START 的 data.inputs.inputs（管理端落库结构）；
    兼容顶层 config.inputs 与旧版 data.outputs 两种历史形态。
    """
    start_node = next(
        (n for n in (canvas_json.get("nodes") or []) if str(n.get("type")) == "1"),
        None,
    )
    if not start_node:
        return []

    data = start_node.get("data") or {}
    raw_items: list[Any] = []
    data_inputs = data.get("inputs")
    if isinstance(data_inputs, dict) and isinstance(data_inputs.get("inputs"), list):
        raw_items.extend(data_inputs["inputs"])
    top_config = start_node.get("config")
    if isinstance(top_config, dict) and isinstance(top_config.get("inputs"), list):
        raw_items.extend(top_config["inputs"])
    if isinstance(data.get("outputs"), list):
        raw_items.extend(data["outputs"])

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("variableName") or "").strip()
        if not name or name in BUILTIN_START_PARAMS or name in seen:
            continue
        seen.add(name)
        param_type = str(item.get("type") or item.get("variableType") or "string").strip()
        result.append({
            "name": name,
            "type": param_type if param_type in _TYPE_LABELS else "string",
            "required": bool(item.get("required", False)),
            "description": str(item.get("description") or ""),
            "default_value": item.get("defaultValue"),
            "order": idx,
        })
    result.sort(key=lambda p: p["order"])
    for p in result:
        p.pop("order")
    return result


def _validate_inputs(
    schema_inputs: list[dict[str, Any]],
    inputs: dict[str, Any],
) -> None:
    """按 START schema 校验必填与顶层类型；未知入参忽略（前端可能带冗余字段）。"""
    if not isinstance(inputs, dict):
        raise ValidationError("入参必须是对象")

    for param in schema_inputs:
        name = param["name"]
        param_type = param["type"]
        present = name in inputs and inputs[name] is not None
        if not present:
            if param["required"] and param.get("default_value") is None:
                raise ValidationError(f"缺少必填入参：{name}")
            continue
        _validate_type(name, param_type, inputs[name])


def _validate_type(name: str, param_type: str, value: Any) -> None:
    if param_type == "string":
        if not isinstance(value, str):
            raise ValidationError(f"入参 {name} 必须是文本")
        return
    if param_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"入参 {name} 必须是数字")
        return
    if param_type == "boolean":
        if not isinstance(value, bool):
            raise ValidationError(f"入参 {name} 必须是布尔值")
        return
    if param_type == "object":
        if not isinstance(value, dict):
            raise ValidationError(f"入参 {name} 必须是对象")
        return
    if param_type in ("file", "image"):
        # 前端上传控件产出 dataURL 字符串；也允许 {url/name} 结构
        if not isinstance(value, str) and not isinstance(value, dict):
            raise ValidationError(f"入参 {name} 必须是{_TYPE_LABELS[param_type]}内容")
        return
    if param_type.startswith("array["):
        if not isinstance(value, list):
            raise ValidationError(f"入参 {name} 必须是数组")
        element_type = param_type[len("array["):-1]
        checker = {
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "object": lambda v: isinstance(v, dict),
        }.get(element_type)
        if checker is not None and not all(checker(v) for v in value):
            raise ValidationError(f"入参 {name} 的元素类型必须是 {element_type}")


class WorkflowService:
    """用户端 workflow 运行编排：鉴权预检 → GraphRuntime → SSE 事件序列。"""

    def __init__(
        self,
        uow: UnitOfWork,
        principal: Any,
        runner_factory: RunnerFactory,
        *,
        app_service: ApplicationService,
        run_repo: RunRepositoryProtocol,
    ) -> None:
        self._uow = uow
        self._principal = principal
        self._runner_factory = runner_factory
        self._tenant_id = principal.tenant_id
        self._user_id = principal.user_id
        self._app_service = app_service
        self._run_repo = run_repo

    # ========== schema ==========
    async def get_workflow_schema(self, application_id: UUID) -> dict[str, Any]:
        """返回动态表单需要的 START 入参定义与人审节点标记。"""
        app_card = self._assert_workflow_application(application_id)
        canvas_json = await self._app_service.get_runtime_graph(application_id, self._tenant_id)
        schema_inputs = extract_start_inputs(canvas_json)
        has_human_approval = any(
            str(node.get("type")) == HUMAN_APPROVAL_NODE_TYPE
            for node in canvas_json.get("nodes") or []
        )
        return {
            "application_id": str(application_id),
            "name": app_card.get("name") or "",
            "description": app_card.get("description") or "",
            "flow_type": app_card.get("flow_type") or "workflow",
            "inputs": schema_inputs,
            "has_human_approval": has_human_approval,
        }

    # ========== 运行 ==========
    async def prepare_workflow_run(
        self,
        application_id: UUID,
        inputs: dict[str, Any],
        thread_id: str | None,
    ) -> WorkflowPreparedRun:
        """流外预检：可见性、形态、问答节点、入参、线程冲突。"""
        self._assert_workflow_application(application_id)
        canvas_json = await self._app_service.get_runtime_graph(application_id, self._tenant_id)

        if any(str(node.get("type")) == QUESTION_NODE_TYPE for node in canvas_json.get("nodes") or []):
            raise ValidationError("工作流中暂不支持问答节点：该节点会中断且没有恢复通道，请改用对话流")

        schema_inputs = extract_start_inputs(canvas_json)
        merged_inputs = self._apply_defaults(schema_inputs, inputs)
        _validate_inputs(schema_inputs, merged_inputs)

        bound_thread_id = (thread_id or "").strip() or None
        if bound_thread_id is not None:
            active = self._run_repo.get_running_by_thread(
                self._tenant_id, application_id, bound_thread_id,
            )
            if active is not None:
                raise ConflictError("该线程已有运行中或等待审批的运行，请等待结束或改用新的运行")

        return WorkflowPreparedRun(
            application_id=application_id,
            canvas_json=canvas_json,
            inputs=merged_inputs,
            thread_id=bound_thread_id,
            schema_inputs=schema_inputs,
        )

    async def run_workflow_stream(
        self,
        prepared: WorkflowPreparedRun,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """执行工作流并产出 SSE 事件：run_start/node_*/llm_token/result/interrupted/error/final。"""

        async def _invoke(runner: Any) -> Any:
            runner.ensure_run(prepared.inputs)
            return await runner.invoke(prepared.inputs)

        async for event, data in self._execute_stream(
            application_id=prepared.application_id,
            thread_id=prepared.thread_id,
            run_id=None,
            run_start_extra={},
            invoke=_invoke,
            error_code="workflow_failed",
            log_label="workflow 运行失败",
        ):
            yield event, data

    # ========== 人审续跑 ==========
    async def prepare_workflow_resume(
        self,
        application_id: UUID,
        thread_id: str,
        *,
        approved: bool,
        comment: str,
    ) -> WorkflowPreparedResume:
        """续跑流外预检：运行存在且处于 interrupted，审批角色 fail-closed。"""
        self._assert_workflow_application(application_id)
        run = self._run_repo.get_running_by_thread(
            self._tenant_id, application_id, thread_id,
        )
        if run is None or run.get("execute_status") != "interrupted":
            raise NotFoundError("没有等待审批的运行记录")

        payload = run.get("interrupt_payload")
        if not isinstance(payload, dict) or not payload:
            # 兜底：DB 无冗余 payload 时从 checkpointer 读
            runner = await self._runner_factory(
                self._app_service,
                self._uow,
                None,
                tenant_id=self._tenant_id,
                application_id=application_id,
                thread_id=thread_id,
                run_id=run["id"],
                current_user_id=self._user_id,
            )
            payload = await runner.get_interrupt_state()
        if not isinstance(payload, dict) or not payload:
            raise ForbiddenError("无法读取人审节点配置，禁止恢复执行")

        required_role = str(payload.get("assignee_role") or "")
        if not required_role:
            raise ForbiddenError("人审节点未配置审批角色，禁止恢复执行")
        self._assert_role_can_approve(required_role)

        return WorkflowPreparedResume(
            application_id=application_id,
            thread_id=thread_id,
            run_id=run["id"],
            approved=approved,
            comment=comment,
            interrupt_payload=payload,
        )

    async def resume_workflow_stream(
        self,
        prepared: WorkflowPreparedResume,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """审批后续跑：批准继续，拒绝由人审节点抛错走 error；可二次中断。"""
        resume_payload = {
            "approved": prepared.approved,
            "comment": prepared.comment,
            "approver": getattr(self._principal, "username", "") or str(self._user_id),
        }

        async for event, data in self._execute_stream(
            application_id=prepared.application_id,
            thread_id=prepared.thread_id,
            run_id=prepared.run_id,
            run_start_extra={"resuming": True},
            invoke=lambda runner: runner.resume(resume_payload),
            error_code="workflow_resume_failed",
            log_label="workflow 续跑失败",
        ):
            yield event, data

    async def _execute_stream(
        self,
        *,
        application_id: UUID,
        thread_id: str | None,
        run_id: UUID | None,
        run_start_extra: dict[str, Any],
        invoke: Callable[[Any], Awaitable[Any]],
        error_code: str,
        log_label: str,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """构造 runner、驱动事件队列、产出 SSE 事件的公共泵（run 与 resume 共用）。"""
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def emitter(event_type: str, payload: dict[str, Any]) -> None:
            await queue.put(("event", (event_type, payload)))

        runner = await self._runner_factory(
            self._app_service,
            self._uow,
            None,
            tenant_id=self._tenant_id,
            application_id=application_id,
            thread_id=thread_id,
            run_id=run_id,
            current_user_id=self._user_id,
            actor_username=getattr(self._principal, "username", None),
            on_node_event=emitter,
        )

        async def run_task() -> None:
            try:
                output = await invoke(runner)
                queue.put_nowait(("output", output))
            except GraphInterrupted as exc:
                queue.put_nowait(("interrupted", exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s application=%s", log_label, application_id)
                queue.put_nowait(("error", exc))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(run_task())
        yield "run_start", {
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
            **run_start_extra,
        }

        try:
            output: Any = None
            interrupted: GraphInterrupted | None = None
            while True:
                kind, payload = await queue.get()
                if kind == "done":
                    break
                if kind == "event":
                    event_type, data = payload
                    yield event_type, data
                elif kind == "output":
                    output = payload
                elif kind == "interrupted":
                    interrupted = payload
                elif kind == "error":
                    yield "error", {"message": str(payload), "code": error_code}
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if interrupted is not None:
            self._uow.commit()
            yield "interrupted", {
                "approval": interrupted.interrupt_payload,
                "thread_id": interrupted.thread_id,
                "run_id": str(runner.run_id),
            }
            yield "final", {}
            return

        self._uow.commit()
        yield "result", {
            "output": output,
            "thread_id": runner.thread_id,
            "run_id": str(runner.run_id),
        }
        yield "final", {}

    # ========== 历史 / 详情 / 待审批 ==========
    def list_runs(self, application_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        """当前用户在某应用下的运行历史（强制按发起人过滤）。"""
        self._assert_workflow_application(application_id)
        rows = self._run_repo.list_runs(
            self._tenant_id,
            workflow_id=application_id,
            user_id=self._user_id,
            limit=min(max(limit, 1), 100),
        )
        return [_serialize_run(row) for row in rows]

    def get_run_detail(self, run_id: UUID) -> dict[str, Any]:
        """运行详情：发起人可看自己的 run；审批人可看待自己审批的中断 run。"""
        run = self._run_repo.get_run(run_id)
        if run is None or run["tenant_id"] != self._tenant_id:
            raise NotFoundError("运行记录不存在")
        if not self._can_access_run(run):
            raise NotFoundError("运行记录不存在")
        return {
            "run": _serialize_run(run),
            "node_executions": [
                _serialize_node_execution(row)
                for row in self._run_repo.list_node_executions(run_id)
            ],
        }

    def list_approvals(self, application_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        """列出等待当前用户角色审批的中断运行；superadmin 看全部。"""
        self._assert_workflow_application(application_id)
        role_code = str(getattr(self._principal, "role_code", "") or "")
        assignee_role = None if role_code == "superadmin" else role_code
        rows = self._run_repo.list_interrupted(
            self._tenant_id,
            application_id,
            assignee_role=assignee_role,
            limit=min(max(limit, 1), 100),
        )
        return [_serialize_run(row) for row in rows]

    # ========== 内部 ==========
    def _assert_workflow_application(self, application_id: UUID) -> dict[str, Any]:
        """可见性闸门 + 形态校验：用户端 workflow 接口拒绝 chatflow。"""
        app_card = self._app_service.assert_user_can_view(
            application_id, self._tenant_id, self._user_id
        )
        if app_card.get("flow_type") == "chatflow":
            raise ValidationError("对话流应用请使用对话流运行接口")
        return app_card

    @staticmethod
    def _apply_defaults(
        schema_inputs: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(inputs)
        for param in schema_inputs:
            if merged.get(param["name"]) is None and param.get("default_value") is not None:
                merged[param["name"]] = param["default_value"]
        return merged

    def _can_access_run(self, run: dict[str, Any]) -> bool:
        if run.get("user_id") == self._user_id:
            return True
        if run.get("execute_status") != "interrupted":
            return False
        payload = run.get("interrupt_payload")
        if not isinstance(payload, dict):
            return False
        required_role = str(payload.get("assignee_role") or "")
        return bool(required_role) and self._role_matches(required_role)

    def _role_matches(self, required_role: str) -> bool:
        """当前 principal 角色是否匹配人审要求角色（superadmin 放行）。"""
        role_code = str(getattr(self._principal, "role_code", "") or "")
        return role_code == "superadmin" or role_code == required_role

    def _assert_role_can_approve(self, required_role: str) -> None:
        if not self._role_matches(required_role):
            role_code = str(getattr(self._principal, "role_code", "") or "")
            raise ForbiddenError(
                f"该人审节点要求角色 {required_role}，当前角色 {role_code} 无权审批"
            )


def _serialize_run(row: dict[str, Any]) -> dict[str, Any]:
    """run 行转 API 响应：datetime 转 isoformat，JSONB 原样透传。"""
    keys = (
        "id", "workflow_id", "user_id", "thread_id", "execute_status",
        "input", "output", "error_message", "interrupt_payload",
        "started_at", "finished_at",
    )
    result: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        result[key] = value.isoformat() if isinstance(value, datetime) else value
    return result


def _serialize_node_execution(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "node_id", "node_type", "input", "output", "error_message",
        "started_at", "finished_at", "duration_ms", "usage",
    )
    result: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        result[key] = value.isoformat() if isinstance(value, datetime) else value
    return result
