"""Code 节点沙箱测试。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.code import CodeNodeHandler
from internal.infrastructure.sandbox.python_sandbox import PythonSandbox


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="code-test",
        application_id=uuid4(),
    )


def test_code_node_stub():
    """未注入 sandbox 时走 stub。"""
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={"input": "hi"},
        config={"code": "def main(args): return args"},
        env=_make_env(),
        services=ServiceRegistry(),
    )
    result = asyncio.run(handler.run(ctx))
    assert "stub" in result.outputs


def test_code_node_executes_user_function():
    """注入真实沙箱后，用户 main 函数被执行。"""
    sandbox = PythonSandbox(timeout_s=5.0)
    services = ServiceRegistry({"sandbox": sandbox})

    user_code = '''
def main(args):
    text = args.get("input", "")
    return {"output": f"echo: {text}", "len": len(text)}
'''
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={"input": "boxia"},
        config={"code": user_code, "timeoutMs": 5000},
        env=_make_env(),
        services=services,
    )
    result = asyncio.run(handler.run(ctx))
    assert result.outputs["output"] == "echo: boxia"
    assert result.outputs["len"] == 5


def test_code_node_timeout_raises():
    """死循环代码应超时并抛异常。"""
    sandbox = PythonSandbox(timeout_s=1.0)
    services = ServiceRegistry({"sandbox": sandbox})

    user_code = '''
def main(args):
    while True:
        pass
    return {}
'''
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={},
        config={"code": user_code, "timeoutMs": 1000},
        env=_make_env(),
        services=services,
    )
    try:
        asyncio.run(handler.run(ctx))
        assert False, "应该抛出 RuntimeError"
    except RuntimeError as exc:
        assert "超时" in str(exc)
