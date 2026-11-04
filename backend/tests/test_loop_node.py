"""Loop 节点集成测试：验证循环体子图能被真正迭代执行。"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from internal.domain.canvas.convert import convert_canvas
from internal.domain.graph.compiler import Compiler
from internal.domain.graph.node_base import RuntimeEnv, ServiceRegistry


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="loop-test-thread",
        application_id=uuid4(),
    )


def _build_loop_canvas() -> dict[str, Any]:
    """构造最小 Loop 画布：START → LOOP → END。

    循环体（blocks）：START → LLM(stub) → END
    """
    return {
        "nodes": [
            {
                "id": "start_1",
                "type": "1",
                "data": {
                    "nodeMeta": {"title": "开始"},
                    "inputs": {
                        "inputParameters": [
                            {
                                "name": "input",
                                "input": {
                                    "type": "array[string]",
                                    "value": {"type": "literal", "content": ["a", "b", "c"]},
                                },
                            }
                        ]
                    },
                    "outputs": [{"name": "input", "type": "array[string]"}],
                },
            },
            {
                "id": "loop_1",
                "type": "21",
                "data": {
                    "nodeMeta": {"title": "循环"},
                    "inputs": {
                        "loopType": "array",
                        "inputParameters": [
                            {
                                "name": "input",
                                "input": {
                                    "type": "array[string]",
                                    "value": {
                                        "type": "ref",
                                        "content": {
                                            "source": "block-output",
                                            "blockID": "start_1",
                                            "name": "input",
                                        },
                                    },
                                },
                            }
                        ],
                    },
                    "outputs": [{"name": "output", "type": "array"}],
                },
                "blocks": [
                    {
                        "id": "loop_start",
                        "type": "1",
                        "data": {
                            "nodeMeta": {"title": "循环开始"},
                            "inputs": {},
                            "outputs": [
                                {"name": "item", "type": "string"},
                                {"name": "index", "type": "number"},
                            ],
                        },
                    },
                    {
                        "id": "loop_llm",
                        "type": "3",
                        "data": {
                            "nodeMeta": {"title": "循环LLM"},
                            "inputs": {
                                "inputParameters": [
                                    {
                                        "name": "input",
                                        "input": {
                                            "type": "string",
                                            "value": {
                                                "type": "ref",
                                                "content": {
                                                    "source": "block-output",
                                                    "blockID": "loop_start",
                                                    "name": "item",
                                                },
                                            },
                                        },
                                    }
                                ],
                                "prompt": "echo: {{input}}",
                            },
                            "outputs": [{"name": "output", "type": "string"}],
                        },
                    },
                    {
                        "id": "loop_end",
                        "type": "2",
                        "data": {
                            "nodeMeta": {"title": "循环结束"},
                            "inputs": {
                                "inputParameters": [
                                    {
                                        "name": "output",
                                        "input": {
                                            "type": "string",
                                            "value": {
                                                "type": "ref",
                                                "content": {
                                                    "source": "block-output",
                                                    "blockID": "loop_llm",
                                                    "name": "output",
                                                },
                                            },
                                        },
                                    }
                                ]
                            },
                        },
                    },
                ],
                "edges": [
                    {
                        "sourceNodeID": "loop_start",
                        "targetNodeID": "loop_llm",
                        "sourcePortID": "source",
                    },
                    {
                        "sourceNodeID": "loop_llm",
                        "targetNodeID": "loop_end",
                        "sourcePortID": "source",
                    },
                ],
            },
            {
                "id": "end_1",
                "type": "2",
                "data": {
                    "nodeMeta": {"title": "结束"},
                    "inputs": {
                        "inputParameters": [
                            {
                                "name": "output",
                                "input": {
                                    "type": "array",
                                    "value": {
                                        "type": "ref",
                                        "content": {
                                            "source": "block-output",
                                            "blockID": "loop_1",
                                            "name": "output",
                                        },
                                    },
                                },
                            }
                        ]
                    },
                },
            },
        ],
        "edges": [
            {"sourceNodeID": "start_1", "targetNodeID": "loop_1", "sourcePortID": "source"},
            {"sourceNodeID": "loop_1", "targetNodeID": "end_1", "sourcePortID": "source"},
        ],
    }


def test_loop_iterates_subgraph():
    """验证 Loop 节点能真正迭代执行循环体子图。"""
    canvas = _build_loop_canvas()
    graph = convert_canvas(canvas)

    # 确认 loop 节点带 subgraph
    loop_node = next(n for n in graph.nodes if n.type.value == "21")
    assert loop_node.subgraph is not None
    assert len(loop_node.subgraph.nodes) == 3  # loop_start / loop_llm / loop_end

    env = _make_env()
    compiler = Compiler(services=ServiceRegistry())
    compiled = compiler.compile(graph, env, checkpointer=None)

    async def _invoke():
        initial_state = {
            "input": {"input": ["a", "b", "c"]},
            "node_outputs": {},
            "globals": {},
            "env": {"tenant_id": str(env.tenant_id)},
            "output": {},
            "errors": {},
        }
        return await compiled.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "loop-test"}},
        )

    result = asyncio.run(_invoke())

    loop_output = result["node_outputs"]["loop_1"]
    assert loop_output["count"] == 3
    assert len(loop_output["output"]) == 3
    # 每次迭代的输出是 LLM stub 文本
    for item in loop_output["output"]:
        assert "output" in item
        assert item["output"].startswith("[LLM stub]")
