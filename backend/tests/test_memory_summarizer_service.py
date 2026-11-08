"""M4 PRD F15.4：MemorySummarizerService 单测（fake LLM + fake 会话仓储）。

契约：任何失败/超时/乐观并发让位都返回 None 且不抛出——摘要链路绝不阻塞对话主流程
（PRD F15.5 失败降级），由调用方沿用旧摘要 + truncate 组合。
异步调用按项目惯例用 asyncio.run 包装（无 pytest-asyncio）。
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from internal.application.apps.memory_service import MemorySummarizerService
from internal.domain.agent.memory import SummarizationPlan
from internal.domain.llm.client import LLMResponse


class _FakeClient:
    """记录调用参数的 LLMClient 替身；response_content/exception 控制返回形态。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.response_content = "合并后的新摘要正文。"
        self.exception: Exception | None = None

    async def chat(
        self, *, messages, tools=None, temperature=None, max_tokens=None, **kwargs
    ) -> LLMResponse:
        self.calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        if self.exception is not None:
            raise self.exception
        return LLMResponse(content=self.response_content)


class _FakeModelService:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.requested: list[tuple[str, UUID]] = []
        self.resolve_error: Exception | None = None

    def get_client_for_tenant(self, model_id: str, tenant_id: UUID) -> _FakeClient:
        self.requested.append((model_id, tenant_id))
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.client


class _FakeConvRepo:
    def __init__(self, write_ok: bool = True) -> None:
        self.write_ok = write_ok
        self.updates: list[dict] = []

    def update_summary_if_marker(
        self, conversation_id: UUID, *, old_marker, summary: str, new_marker
    ) -> bool:
        self.updates.append(
            {"id": conversation_id, "old": old_marker, "summary": summary, "new": new_marker}
        )
        return self.write_ok


def _plan(n_rows: int = 2) -> SummarizationPlan:
    rows = [{"id": f"m{i}", "role": "user", "content": f"问{i}"} for i in range(n_rows)]
    return SummarizationPlan(
        should_summarize=True, to_compress=rows, retained=[], new_marker=rows[-1]["id"]
    )


def _service(model_service: _FakeModelService, conv_repo: _FakeConvRepo) -> MemorySummarizerService:
    return MemorySummarizerService(model_service=model_service, conv_repo=conv_repo)  # type: ignore[arg-type]


_MEMORY = {
    "strategy": "summarize",
    "keepRecentTurns": 6,
    "maxSummaryChars": 1500,
    "summarizeModel": None,
}


def _refresh(service: MemorySummarizerService, **kwargs) -> str | None:
    return asyncio.run(service.refresh_summary(**kwargs))


def test_summarize_success_writes_back_and_returns_text() -> None:
    """成功路径：temperature 0、模型默认走应用主模型、乐观锁参数原样透传。"""
    client = _FakeClient()
    model_service = _FakeModelService(client)
    conv_repo = _FakeConvRepo()
    tenant_id = uuid4()
    cid = uuid4()
    new = _refresh(
        _service(model_service, conv_repo),
        conversation_id=cid,
        tenant_id=tenant_id,
        plan=_plan(),
        old_summary="旧摘要",
        memory=_MEMORY,
        default_model_id="deepseek-chat",
        watermark_id="m0",
    )
    assert new == "合并后的新摘要正文。"
    assert model_service.requested == [("deepseek-chat", tenant_id)]
    call = client.calls[0]
    assert call["temperature"] == 0
    assert call["messages"][0]["role"] == "system"
    assert "旧摘要" in call["messages"][1]["content"]
    assert "问0" in call["messages"][1]["content"] and "问1" in call["messages"][1]["content"]
    assert conv_repo.updates == [
        {"id": cid, "old": "m0", "summary": "合并后的新摘要正文。", "new": "m1"}
    ]


def test_summarize_model_prefers_configured_summarize_model() -> None:
    """配置了 summarizeModel 时不走应用主模型（PRD F15.4 可配低成本模型）。"""
    client = _FakeClient()
    model_service = _FakeModelService(client)
    _refresh(
        _service(model_service, _FakeConvRepo()),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=_plan(),
        old_summary=None,
        memory={**_MEMORY, "summarizeModel": "small-fast-model"},
        default_model_id="deepseek-chat",
        watermark_id=None,
    )
    assert model_service.requested[0][0] == "small-fast-model"


def test_no_plan_skips_llm_and_returns_none() -> None:
    """频控未触发（无待压缩段）：不发起任何 LLM 调用。"""
    client = _FakeClient()
    model_service = _FakeModelService(client)
    conv_repo = _FakeConvRepo()
    result = _refresh(
        _service(model_service, conv_repo),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=SummarizationPlan(should_summarize=False),
        old_summary="旧摘要",
        memory=_MEMORY,
        default_model_id="deepseek-chat",
        watermark_id="m0",
    )
    assert result is None
    assert client.calls == []
    assert conv_repo.updates == []


def test_llm_failure_degrades_to_none() -> None:
    """LLM 异常（超时/网关错误）：不抛出、不回写——上层降级旧摘要+truncate。"""
    client = _FakeClient()
    client.exception = RuntimeError("gateway timeout")
    model_service = _FakeModelService(client)
    conv_repo = _FakeConvRepo()
    result = _refresh(
        _service(model_service, conv_repo),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=_plan(),
        old_summary=None,
        memory=_MEMORY,
        default_model_id="deepseek-chat",
        watermark_id=None,
    )
    assert result is None
    assert conv_repo.updates == []


def test_model_resolve_failure_degrades_to_none() -> None:
    """模型未配置（解析异常）：同样降级，不阻塞对话。"""
    client = _FakeClient()
    model_service = _FakeModelService(client)
    model_service.resolve_error = ValueError("模型未配置")
    conv_repo = _FakeConvRepo()
    result = _refresh(
        _service(model_service, conv_repo),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=_plan(),
        old_summary=None,
        memory=_MEMORY,
        default_model_id="deepseek-chat",
        watermark_id=None,
    )
    assert result is None
    assert conv_repo.updates == []


def test_optimistic_lock_loss_returns_none() -> None:
    """水位线被并发轮次前移（回写 0 行）：本轮让位，返回 None 不报错。"""
    client = _FakeClient()
    model_service = _FakeModelService(client)
    conv_repo = _FakeConvRepo(write_ok=False)
    result = _refresh(
        _service(model_service, conv_repo),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=_plan(),
        old_summary=None,
        memory=_MEMORY,
        default_model_id="deepseek-chat",
        watermark_id=None,
    )
    assert result is None


def test_oversized_output_hard_truncated() -> None:
    """模型不守 maxSummaryChars：服务侧硬截断到配置字数（提示词软约束+代码硬约束）。"""
    client = _FakeClient()
    client.response_content = "超" * 3000
    model_service = _FakeModelService(client)
    conv_repo = _FakeConvRepo()
    result = _refresh(
        _service(model_service, conv_repo),
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        plan=_plan(),
        old_summary=None,
        memory={**_MEMORY, "maxSummaryChars": 1500},
        default_model_id="deepseek-chat",
        watermark_id=None,
    )
    assert result is not None
    assert len(result) <= 1500
    assert conv_repo.updates[0]["summary"] == result
