"""T18：LLM 节点多模态（image_url content part）单测。

验证：
1. 无图片时 user content 是纯字符串（向后兼容）
2. inputs["images"] 传入图片 URL 列表时，user content 是 multi-modal parts 数组
3. config["images"] 也能作为兜底来源
4. 非字符串元素被过滤
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.llm import LLMNodeHandler


class _Resp:
    def __init__(self, content: str = "ok") -> None:
        self.content = content
        self.tool_calls = []
        self.usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)


class _ScriptedLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, *, messages, **kwargs) -> _Resp:
        self.calls.append({"messages": messages})
        return _Resp("好的")


def _make_ctx(services: ServiceRegistry, inputs: dict, config: dict) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="llm_1",
        node_type=NodeType.LLM.value,
        inputs=inputs,
        config=config,
        env=env,
        services=services,
        emit_event=None,
    )


def _run(inputs: dict, config: dict) -> tuple[dict, _ScriptedLLM]:
    llm = _ScriptedLLM()
    services = ServiceRegistry({"llm": llm})
    ctx = _make_ctx(services, inputs, config)
    result = asyncio.run(LLMNodeHandler().run(ctx))
    return result, llm


def test_user_content_is_plain_string_when_no_images():
    _, llm = _run(
        inputs={"input": "你好"},
        config={"modleName": "gpt-4o", "prompt": "你好"},
    )
    user_msg = llm.calls[0]["messages"][-1]
    assert isinstance(user_msg["content"], str)
    assert "你好" in user_msg["content"]


def test_user_content_includes_image_url_parts_from_inputs():
    _, llm = _run(
        inputs={
            "input": "描述这张图",
            "images": ["https://example.com/a.png", "data:image/png;base64,xx"],
        },
        config={"modleName": "gpt-4o", "prompt": "描述这张图"},
    )
    user_msg = llm.calls[0]["messages"][-1]
    content = user_msg["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "描述这张图"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/a.png"},
    }
    assert content[2]["type"] == "image_url"


def test_config_images_fallback_when_inputs_missing():
    _, llm = _run(
        inputs={"input": "看图"},
        config={
            "modleName": "gpt-4o",
            "prompt": "看图",
            "images": ["https://example.com/b.png"],
        },
    )
    user_msg = llm.calls[0]["messages"][-1]
    content = user_msg["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"


def test_non_string_images_are_filtered():
    _, llm = _run(
        inputs={"input": "x", "images": ["https://example.com/c.png", 123, None, ""]},
        config={"modleName": "gpt-4o", "prompt": "x"},
    )
    user_msg = llm.calls[0]["messages"][-1]
    content = user_msg["content"]
    # 只保留 1 个有效 URL
    assert isinstance(content, list)
    image_parts = [p for p in content if p["type"] == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == "https://example.com/c.png"


def test_single_string_image_wrapped():
    _, llm = _run(
        inputs={"input": "x", "images": "https://example.com/d.png"},
        config={"modleName": "gpt-4o", "prompt": "x"},
    )
    user_msg = llm.calls[0]["messages"][-1]
    content = user_msg["content"]
    assert isinstance(content, list)
    assert content[1]["image_url"]["url"] == "https://example.com/d.png"
