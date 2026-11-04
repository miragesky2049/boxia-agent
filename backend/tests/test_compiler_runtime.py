"""Compiler + Runtime 集成测试（阶段 1 最小闭环）。

不连数据库，用 checkpointer=None 测试编译和执行逻辑。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from internal.domain.canvas.convert import convert_canvas
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import RuntimeEnv, ServiceRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )


def test_start_exit_compile_and_invoke():
    """start_exit.json: START → END，验证最小闭环能跑通。"""
    canvas_json = _load("start_exit.json")
    graph = convert_canvas(canvas_json)

    env = _make_env()
    compiler = Compiler(services=ServiceRegistry())
    compiled = compiler.compile(graph, env, checkpointer=None)

    async def _invoke():
        initial_state = {
            "input": {"USER_INPUT": "你好"},
            "node_outputs": {},
            "globals": {},
            "env": {"tenant_id": str(env.tenant_id)},
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-thread"}},
        )

    result = _run(_invoke())

    output = result.get("output", {})
    assert "output" in output
    assert output["output"] == "你好"


def test_llm_chat_with_stub_service():
    """llm_chat.json: START → LLM(stub) → END，验证 LLM 节点走 stub 分支。"""
    canvas_json = _load("llm_chat.json")
    graph = convert_canvas(canvas_json)

    env = _make_env()
    compiler = Compiler(services=ServiceRegistry())
    compiled = compiler.compile(graph, env, checkpointer=None)

    async def _invoke():
        initial_state = {
            "input": {"USER_INPUT": "测试问题"},
            "node_outputs": {},
            "globals": {},
            "env": {"tenant_id": str(env.tenant_id)},
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-thread-2"}},
        )

    result = _run(_invoke())

    output = result.get("output", {})
    assert "output" in output
    assert output["output"].startswith("[LLM stub]")


def test_llm_node_with_mock_service():
    """注册 mock llm 服务，验证 LLM 节点真实调用路径。"""

    class MockLLMService:
        async def chat(self, messages, model, temperature, max_tokens, response_format):
            class Usage:
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            class Resp:
                def __init__(self):
                    self.content = f"mock response to: {messages[-1]['content']}"
                    self.model = model
                    self.usage = Usage()

            return Resp()

    services = ServiceRegistry({"llm": MockLLMService()})

    canvas_json = _load("llm_chat.json")
    graph = convert_canvas(canvas_json)

    env = _make_env()
    compiler = Compiler(services=services)
    compiled = compiler.compile(graph, env, checkpointer=None)

    async def _invoke():
        initial_state = {
            "input": {"USER_INPUT": "介绍一下你自己"},
            "node_outputs": {},
            "globals": {},
            "env": {"tenant_id": str(env.tenant_id)},
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-thread-3"}},
        )

    result = _run(_invoke())

    output = result.get("output", {})
    assert "介绍一下你自己" in output["output"]

    node_outputs = result.get("node_outputs", {})
    llm_output = node_outputs.get("123887", {})
    assert "output" in llm_output
