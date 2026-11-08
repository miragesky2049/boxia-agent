"""GraphRuntime 端到端测试：用 mock 服务 + 内存 repo 验证编译、执行、节点明细、usage 落库。

不连数据库，checkpointer=None，repo 用 Fake 实现。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from internal.domain.graph.node_base import ServiceRegistry
from internal.domain.graph.runtime import GraphRuntime

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeLLMService:
    """模拟 LLM 节点期望的 chat 接口。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self, *, messages, model, temperature=None, max_tokens=None, response_format=None
    ):
        self.calls.append({"messages": messages, "model": model})
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        return SimpleNamespace(
            content=f"fake reply to: {messages[-1]['content']}",
            model=model,
            usage=usage,
        )


class FakeRunRepo:
    def __init__(self) -> None:
        self.inserted_runs: list[dict] = []
        self.node_executions: list[dict] = []
        self.status_updates: list[dict] = []

    def insert_run(self, **kwargs):
        self.inserted_runs.append(kwargs)

    def update_run_status(self, run_id, execute_status, output=None, error_message=None):
        self.status_updates.append(
            {"run_id": run_id, "status": execute_status, "output": output, "error": error_message}
        )

    def update_run_interrupt(self, run_id, payload):
        self.status_updates.append({"run_id": run_id, "status": "interrupted", "payload": payload})

    def insert_node_execution(self, **kwargs):
        self.node_executions.append(kwargs)


class FakeUsageRepo:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record_usage(self, **kwargs):
        self.records.append(kwargs)


def test_runtime_invokes_llm_graph_writes_records():
    canvas_json = _load("llm_chat.json")
    llm = FakeLLMService()
    run_repo = FakeRunRepo()
    usage_repo = FakeUsageRepo()

    services = ServiceRegistry({"llm": llm})
    runtime = GraphRuntime(
        canvas_json=canvas_json,
        services=services,
        run_repo=run_repo,
        usage_repo=usage_repo,
        tenant_id=uuid4(),
        user_id=uuid4(),
        application_id=uuid4(),
        checkpointer=None,
    )

    output = asyncio.run(runtime.invoke({"USER_INPUT": "你好"}))

    assert "你好" in output.get("output", "")
    assert llm.calls, "llm 服务应被调用"
    assert run_repo.inserted_runs, "run_repo.insert_run 应被调用"
    assert any(u["status"] == "success" for u in run_repo.status_updates), "应写 success 状态"
    assert run_repo.node_executions, "应写节点执行明细"
    assert usage_repo.records, "LLM 节点应写 usage ledger"
    assert usage_repo.records[0]["total_tokens"] == 30


def test_runtime_handles_llm_failure_writes_audit():
    """LLM 抛异常时，runtime 应更新 run 状态为 error 并写 audit。

    注意：fixture 默认 settingOnError.processType=1（降级跳过），
    这里显式改成 processType=0（中断），验证 run 级失败路径。
    """

    class BrokenLLM:
        async def chat(self, **kwargs):
            raise RuntimeError("boom")

    class FakeAuditRepo:
        def __init__(self) -> None:
            self.records: list[dict] = []

        def record(self, payload):
            self.records.append(payload)

    canvas_json = _load("llm_chat.json")
    # 显式改成中断策略，让 LLM 失败时整个 run 失败
    for node in canvas_json.get("nodes", []):
        if str(node.get("type")) == "3":
            inputs = node.get("data", {}).get("inputs", {})
            if "settingOnError" in inputs:
                inputs["settingOnError"]["processType"] = 0
    run_repo = FakeRunRepo()
    audit_repo = FakeAuditRepo()

    runtime = GraphRuntime(
        canvas_json=canvas_json,
        services=ServiceRegistry({"llm": BrokenLLM()}),
        run_repo=run_repo,
        audit_repo=audit_repo,
        tenant_id=uuid4(),
        user_id=uuid4(),
        application_id=uuid4(),
        checkpointer=None,
    )

    try:
        asyncio.run(runtime.invoke({"USER_INPUT": "test"}))
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert any(u["status"] == "error" for u in run_repo.status_updates)
    assert audit_repo.records, "error 时应写 audit"
