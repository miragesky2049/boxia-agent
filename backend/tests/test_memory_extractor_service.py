"""M4 PRD F16.3：MemoryExtractorService 单测（fake LLM + duck-type 仓储）。

契约：add/update/delete 合并指令执行、source_run_id 幂等、关闭态零开销、
容量收口仅在有新增时触发。异步入口按项目惯例 asyncio.run 包装。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.application.apps.memory_service import MemoryExtractorService
from internal.application.apps.model_service import ModelService  # noqa: F401  类型占位参考


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, temperature=None, **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature})

        class _Resp:
            pass

        resp = _Resp()
        resp.content = self.content
        return resp


class _FakeModelService:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.requested: list[str] = []

    def get_client_for_tenant(self, model_id, tenant_id) -> _FakeClient:
        self.requested.append(model_id)
        return self.client


class _RunRepo:
    def __init__(self, run: dict | None) -> None:
        self._run = run
        self.merged: list[dict] = []

    def get_run(self, run_id):
        return self._run

    def merge_run_output(self, run_id, patch):
        self.merged.append({"run_id": run_id, **patch})
        return True


class _MsgRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list_messages_by_run(self, run_id):
        return self._rows


class _ConvRepo:
    def get_conversation(self, conversation_id):
        return {"summary": "此前讨论了退款。"}


class _MemoryRepo:
    def __init__(self, existing: list[dict] | None = None, extracted: bool = False) -> None:
        self.existing = existing or []
        self._extracted = extracted
        self.inserted: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[dict] = []
        self.overflow_calls: list[int] = []

    def exists_by_source_run(self, source_run_id):
        return self._extracted

    def list_active(self, *, tenant_id, application_id, user_id, limit=20):
        return self.existing[:limit]

    def insert(self, **kwargs):
        self.inserted.append(kwargs)
        return uuid4()

    def update_content(self, memory_id, *, content, kind=None):
        self.updated.append({"id": memory_id, "content": content, "kind": kind})
        return True

    def delete_scoped(self, memory_id, *, tenant_id, user_id, application_id=None):
        self.deleted.append(memory_id)
        return True

    def archive_overflow(self, *, tenant_id, application_id, user_id, max_active):
        self.overflow_calls.append(max_active)
        return 0


def _canvas_graph(long_term: dict[str, Any] | None) -> dict:
    def literal(value: object) -> dict:
        return {"value": {"type": "literal", "content": value}}

    memory: dict[str, Any] = {"shortTerm": {"strategy": "truncate"}}
    if long_term is not None:
        memory["longTerm"] = long_term
    return {
        "nodes": [
            {
                "id": "loop_1",
                "type": "100",
                "data": {
                    "inputs": {"modleName": literal("m-main"), "memory": literal(memory)},
                    "outputs": [],
                },
            }
        ],
        "edges": [],
    }


def _service(
    *,
    content: str,
    long_term: dict[str, Any] | None = None,
    existing: list[dict] | None = None,
    extracted: bool = False,
    run: dict | None = "auto",
):
    tenant_id, app_id, user_id = uuid4(), uuid4(), uuid4()
    if run == "auto":
        run_row = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "workflow_id": app_id,
            "user_id": user_id,
            "thread_id": f"{uuid4()}",
            # M4 PRD F16.3（review 修正）：抽取按 run 快照判定配置，与对话执行同源
            "graph_snapshot": _canvas_graph(long_term),
        }
    else:
        run_row = run
    conv_id = (run_row or {}).get("thread_id", "").split(":")[0] or None
    msg_rows = [
        {
            "id": uuid4(),
            "conversation_id": conv_id,
            "role": "user",
            "content": "我以后都只要中文回复",
        },
        {"id": uuid4(), "conversation_id": conv_id, "role": "assistant", "content": "好的。"},
    ]
    client = _FakeClient(content)
    model_service = _FakeModelService(client)
    memory_repo = _MemoryRepo(existing=existing, extracted=extracted)
    service = MemoryExtractorService(
        model_service=model_service,  # type: ignore[arg-type]
        run_repo=_RunRepo(run_row),
        msg_repo=_MsgRepo(msg_rows),
        conv_repo=_ConvRepo(),
        memory_repo=memory_repo,
        default_model_id="default-m",
    )
    run_id = (run_row or {}).get("id", uuid4())
    return service, memory_repo, model_service, run_id


_ENABLED = {"enabled": True, "recallTopK": 5, "maxMemories": 200}


def test_add_op_inserts_with_source_run_and_capacity_sweep() -> None:
    service, mem, models, run_id = _service(
        long_term=_ENABLED,
        content='[{"op": "add", "kind": "preference", "content": "用户要求只用中文回复"}]',
    )
    counts = asyncio.run(service.extract_for_run(run_id))
    assert counts == {"added": 1, "updated": 0, "deleted": 0}
    assert mem.inserted[0]["kind"] == "preference"
    assert mem.inserted[0]["source_run_id"] == run_id
    assert mem.overflow_calls == [200]
    # 未配 extractModel：回退应用主模型（画布 modleName），而不是 settings 默认
    assert models.requested == ["m-main"]
    # M4 F16.7：抽取计数 additive 回写 run.output
    assert service._run_repo.merged == [{"run_id": run_id, "memory_extract": counts}]


def test_update_and_delete_ops_applied() -> None:
    target = uuid4()
    drop = uuid4()
    service, mem, _, run_id = _service(
        long_term=_ENABLED,
        existing=[
            {"id": target, "kind": "fact", "content": "旧地址"},
            {"id": drop, "kind": "fact", "content": "旧手机号"},
        ],
        content=(
            f'[{{"op": "update", "memory_id": "{target}", "kind": "fact", "content": "现居杭州"}},'
            f' {{"op": "delete", "memory_id": "{drop}"}}]'
        ),
    )
    counts = asyncio.run(service.extract_for_run(run_id))
    assert counts == {"added": 0, "updated": 1, "deleted": 1}
    assert mem.updated[0]["id"] == target and mem.updated[0]["content"] == "现居杭州"
    assert mem.deleted == [drop]
    # 无新增：不做容量收口
    assert mem.overflow_calls == []
    # 有变更仍回写计数（观测口径含 update/delete）
    assert service._run_repo.merged[0]["memory_extract"] == counts


def test_existing_memories_and_summary_passed_into_prompt() -> None:
    service, _, models, run_id = _service(
        long_term=_ENABLED,
        content="[]",
        existing=[
            {"id": uuid4(), "kind": "preference", "content": "喜欢简洁"},
        ],
    )
    asyncio.run(service.extract_for_run(run_id))
    user_content = models.client.calls[0]["messages"][1]["content"]
    assert "喜欢简洁" in user_content
    assert "此前讨论了退款。" in user_content
    assert models.client.calls[0]["temperature"] == 0


def test_idempotent_rerun_skips_without_llm() -> None:
    service, _, models, run_id = _service(
        long_term=_ENABLED, content='[{"op":"add","kind":"fact","content":"x"}]', extracted=True
    )
    counts = asyncio.run(service.extract_for_run(run_id))
    assert counts == {"added": 0, "updated": 0, "deleted": 0}
    assert models.client.calls == []


def test_disabled_or_missing_config_zero_overhead() -> None:
    service, _, models, run_id = _service(long_term={"enabled": False}, content="[")
    assert asyncio.run(service.extract_for_run(run_id)) == {"added": 0, "updated": 0, "deleted": 0}
    assert models.client.calls == []

    service2, _, models2, run_id2 = _service(long_term=None, content="[]")
    assert asyncio.run(service2.extract_for_run(run_id2))["added"] == 0
    assert models2.client.calls == []


def test_extract_model_override_preferred() -> None:
    service, _, models, run_id = _service(
        long_term={**_ENABLED, "extractModel": "cheap-model"}, content="[]"
    )
    asyncio.run(service.extract_for_run(run_id))
    assert models.requested == ["cheap-model"]


def test_missing_run_or_user_skips() -> None:
    service, _, models, _ = _service(long_term=_ENABLED, content="[]", run=None)
    asyncio.run(service.extract_for_run(uuid4()))
    assert models.client.calls == []


def test_missing_graph_snapshot_skips() -> None:
    """review 修正回归：run 快照缺失按未启用处理，零 LLM 调用（不再回源猜版本）。"""
    tenant_id, app_id, user_id = uuid4(), uuid4(), uuid4()
    run_row = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "workflow_id": app_id,
        "user_id": user_id,
        "thread_id": f"{uuid4()}",
    }
    service, _, models, _ = _service(long_term=_ENABLED, content="[]", run=run_row)
    counts = asyncio.run(service.extract_for_run(run_row["id"]))
    assert counts == {"added": 0, "updated": 0, "deleted": 0}
    assert models.client.calls == []


def test_update_without_kind_preserves_original() -> None:
    """review 修正回归：update 缺 kind 传 None 给仓储，由 COALESCE 保留原分类。"""
    target = uuid4()
    service, mem, _, run_id = _service(
        long_term=_ENABLED,
        content=f'[{{"op":"update","memory_id":"{target}","content":"用户偏好详细回复"}}]',
    )
    counts = asyncio.run(service.extract_for_run(run_id))
    assert counts == {"added": 0, "updated": 1, "deleted": 0}
    assert mem.updated[0]["kind"] is None
