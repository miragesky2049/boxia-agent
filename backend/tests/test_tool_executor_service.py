"""T1：ToolExecutorService 单测。

覆盖：
1. 未注册工具返回 "[error] 工具未注册" 并列出可用工具。
2. 已注册工具被正确调用，agent 上下文身份字段透传。
3. ToolExecutionError 转文本 observation，不抛给主循环。
4. 其他异常也转文本 observation，不抛给主循环。
5. 默认注入内置 echo 工具。
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.agent.run_context import AgentRunContext
from internal.domain.llm.client import LLMToolSpec
from internal.domain.agent.tool_gateway import ToolExecutionError
from internal.domain.agent.tool_executor import ToolExecutorService
from internal.domain.agent.tools import Tool


class FakeTool(Tool):
    """测试用桩工具：记录传入的 args/context，按预设行为返回。"""

    def __init__(
        self,
        name: str,
        behavior: str = "ok",
        payload: str = "fake-result",
    ) -> None:
        self._name = name
        self._behavior = behavior
        self._payload = payload
        self.last_args: dict[str, Any] | None = None
        self.last_context: AgentRunContext | None = None

    @property
    def name(self) -> str:
        return self._name

    def spec(self) -> LLMToolSpec:
        return LLMToolSpec(name=self._name, description="", parameters={})

    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        self.last_args = arguments
        self.last_context = context
        if self._behavior == "raise_execution":
            raise ToolExecutionError("工具业务校验失败")
        if self._behavior == "raise_other":
            raise RuntimeError("boom")
        return self._payload


def _make_executor() -> ToolExecutorService:
    """构造 executor，但绕过 _ensure_loaded，直接塞 fake 工具集。"""
    executor = ToolExecutorService(
        session=None,  # noqa: S106 - 测试场景不依赖 session
        tenant_id=uuid4(),
        user_id=uuid4(),
        application_id=uuid4(),
        run_id=uuid4(),
    )
    return executor


def test_unknown_tool_returns_error_with_listing():
    executor = _make_executor()
    known = FakeTool("weather.get")
    executor._tools_cache = {known.name: known}  # type: ignore[assignment]

    observation = asyncio.run(executor("not.exist", {}))

    assert "[error]" in observation
    assert "not.exist" in observation
    assert "weather.get" in observation


def test_known_tool_invoked_with_args_and_context():
    executor = _make_executor()
    weather = FakeTool("weather.get", payload="25°C")
    executor._tools_cache = {"weather.get": weather}  # type: ignore[assignment]

    observation = asyncio.run(executor("weather.get", {"city": "北京"}))

    assert observation == "25°C"
    assert weather.last_args == {"city": "北京"}
    assert weather.last_context is not None
    assert weather.last_context.tenant_id == executor._tenant_id
    assert weather.last_context.user_id == executor._user_id
    assert weather.last_context.agent_id == executor._application_id


def test_tool_execution_error_converted_to_text():
    executor = _make_executor()
    bad = FakeTool("bad.tool", behavior="raise_execution")
    executor._tools_cache = {"bad.tool": bad}  # type: ignore[assignment]

    observation = asyncio.run(executor("bad.tool", {}))

    assert "[error]" in observation
    assert "工具业务校验失败" in observation


def test_unexpected_exception_converted_to_text():
    executor = _make_executor()
    boom = FakeTool("boom.tool", behavior="raise_other")
    executor._tools_cache = {"boom.tool": boom}  # type: ignore[assignment]

    observation = asyncio.run(executor("boom.tool", {}))

    assert "[error]" in observation
    assert "boom" in observation


def test_echo_tool_available_by_default(monkeypatch):
    """当数据库加载不到任何工具时，内置 echo 仍可用。"""
    executor = _make_executor()

    class _EmptyRepo:
        def list_page(self, **_kwargs):  # noqa: ANN003
            return [], 0

    monkeypatch.setattr(
        "internal.domain.agent.tool_executor.PostgresToolRepository",
        lambda *args, **kwargs: _EmptyRepo(),
    )

    observation = asyncio.run(executor("echo", {"text": "hi"}))

    assert "echo: hi" == observation
